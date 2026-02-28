import io
import json
import hashlib
import pathlib
import httpx
import streamlit as st
from datetime import datetime

# ── 상수 ──────────────────────────────────────────────────────────────────────
MAX_LOGIN_ATTEMPTS = 5
DATA_DIR      = pathlib.Path("data")
PENDING_FILE  = DATA_DIR / "pending_users.json"
APPROVED_FILE = DATA_DIR / "approved_users.json"
ADMIN_CREDS_FILE = DATA_DIR / "admin_credentials.json"  # 앱 내 계정 변경 저장소

MODELS          = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
VOICES_MINI_TTS = ["cedar", "marin", "alloy", "ash", "ballad", "coral",
                   "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
VOICES_LEGACY   = ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]

VOICE_GENDER = {
    "cedar": "M", "marin": "F", "alloy": "N", "ash": "M",
    "ballad": "M", "coral": "F", "echo": "M", "fable": "M",
    "nova": "F", "onyx": "M", "sage": "F", "shimmer": "F", "verse": "M",
}
GENDER_EMOJI = {"M": "👨", "F": "👩", "N": "🧑"}
GENDER_LABEL = {"M": "남성", "F": "여성", "N": "중성"}
GENDER_BG    = {"M": "#3A8EDB", "F": "#E8529A", "N": "#F0F0F0"}
GENDER_FG    = {"M": "#FFFFFF",  "F": "#FFFFFF",  "N": "#444444"}

VOICE_DESCRIPTIONS = {
    "cedar":   "따뜻하고 자연스러운 목소리 ⭐ 권장",
    "marin":   "명료하고 차분한 목소리 ⭐ 권장",
    "alloy":   "중성적이고 안정감 있는 목소리",
    "ash":     "자신감 있고 또렷한 목소리",
    "ballad":  "부드럽고 서정적인 목소리",
    "coral":   "밝고 친근한 목소리",
    "echo":    "깊이 있고 차분한 목소리",
    "fable":   "이야기하듯 따뜻한 목소리",
    "nova":    "활기차고 명랑한 목소리",
    "onyx":    "묵직하고 권위 있는 목소리",
    "sage":    "지적이고 사려 깊은 목소리",
    "shimmer": "부드럽고 섬세한 목소리",
    "verse":   "다재다능하고 표현력 있는 목소리",
}
MODEL_DESCRIPTIONS = {
    "gpt-4o-mini-tts": "최신 · 최고품질 · 말투/감정 지시 가능 (권장)",
    "tts-1":           "빠른 응답 · 저지연",
    "tts-1-hd":        "고품질 · 느린 응답",
}

# ── 페이지 기본 설정 ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OpenAI TTS 나레이션 생성기",
    page_icon="🎙️",
    layout="wide",
)

# ── 데이터 헬퍼 ───────────────────────────────────────────────────────────────

def load_json(path: pathlib.Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_json(path: pathlib.Path, data: list) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 인증 헬퍼 ─────────────────────────────────────────────────────────────────

def _load_admin_overrides() -> dict:
    """앱 내에서 변경된 관리자 계정 정보 로드. {username: {name, password}}"""
    if not ADMIN_CREDS_FILE.exists():
        return {}
    try:
        return json.loads(ADMIN_CREDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_admin_override(username: str, name: str, pw_hash: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    overrides = _load_admin_overrides()
    overrides[username] = {"name": name, "password": pw_hash}
    ADMIN_CREDS_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _hash_password(password: str) -> str:
    try:
        pepper = st.secrets["auth"]["pepper"]
    except (KeyError, TypeError):
        pepper = ""
    return hashlib.sha256((password + pepper).encode("utf-8")).hexdigest()


def _secrets_users() -> dict:
    try:
        return dict(st.secrets["users"])
    except (KeyError, TypeError):
        return {}


def verify_login(username: str, password: str) -> tuple[bool, str, bool]:
    """(성공, 표시이름, 관리자여부) 반환."""
    pw_hash   = _hash_password(password)
    overrides = _load_admin_overrides()

    # 1) secrets.toml 계정 → 관리자 (앱 내 변경이 있으면 우선 적용)
    sec = _secrets_users()
    if username in sec:
        if username in overrides:
            # 앱 내에서 변경된 비밀번호 사용
            if pw_hash == overrides[username].get("password", ""):
                return True, overrides[username].get("name", username), True
        else:
            if pw_hash == sec[username].get("password", ""):
                return True, sec[username].get("name", username), True
        return False, "", False

    # 2) approved_users.json → 일반 사용자
    for user in load_json(APPROVED_FILE):
        if user["username"] == username:
            if pw_hash == user.get("password", ""):
                return True, user.get("name", username), False
            return False, "", False

    return False, "", False


def get_api_key() -> str:
    try:
        key = str(st.secrets["openai"]["api_key"]).strip()
    except (KeyError, TypeError):
        return ""
    if not key or "REPLACE_WITH" in key:
        return ""
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        return "__INVALID_KEY__"
    return key


def _all_usernames() -> set:
    pending  = {u["username"] for u in load_json(PENDING_FILE)}
    approved = {u["username"] for u in load_json(APPROVED_FILE)}
    secrets  = set(_secrets_users().keys())
    return pending | approved | secrets


# ── 사이드바 공통 (로그인 상태) ───────────────────────────────────────────────

def _render_sidebar_header():
    with st.sidebar:
        is_admin = st.session_state.get("is_admin", False)
        icon = "👑" if is_admin else "👤"
        st.markdown(f"{icon} **{st.session_state.display_name}**")
        if is_admin:
            st.caption("관리자 계정")

        if st.button("로그아웃", use_container_width=True):
            for k in ["logged_in", "username", "display_name",
                      "is_admin", "login_attempts", "current_page"]:
                st.session_state.pop(k, None)
            st.rerun()

        if is_admin:
            cur = st.session_state.get("current_page", "tts")
            st.divider()
            if cur == "tts":
                if st.button("⚙️ 관리자 페이지", use_container_width=True):
                    st.session_state.current_page = "admin"
                    st.rerun()
            else:
                if st.button("🎙️ TTS 생성기", use_container_width=True):
                    st.session_state.current_page = "tts"
                    st.rerun()


# ── 로그인 화면 ───────────────────────────────────────────────────────────────

def show_login_page():
    if "login_attempts" not in st.session_state:
        st.session_state.login_attempts = 0

    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🔐 로그인")
        st.caption("인가된 사용자만 접근할 수 있습니다.")
        st.markdown("<br>", unsafe_allow_html=True)

        if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
            st.error(
                f"⛔ 로그인 시도를 {MAX_LOGIN_ATTEMPTS}회 초과했습니다.  \n"
                "브라우저를 새로고침하거나 관리자에게 문의하세요."
            )
            return

        with st.form("login_form", clear_on_submit=False):
            username  = st.text_input("아이디", placeholder="username")
            password  = st.text_input("비밀번호", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

        if submitted:
            if not username.strip() or not password:
                st.warning("⚠️ 아이디와 비밀번호를 모두 입력해 주세요.")
                return

            ok, name, is_admin = verify_login(username.strip(), password)
            if ok:
                st.session_state.logged_in    = True
                st.session_state.username     = username.strip()
                st.session_state.display_name = name
                st.session_state.is_admin     = is_admin
                st.session_state.login_attempts = 0
                st.session_state.current_page = "tts"
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                remaining = MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts
                st.error(
                    f"❌ 아이디 또는 비밀번호가 올바르지 않습니다.  \n"
                    f"남은 시도 횟수: **{remaining}회**"
                )

        st.markdown("<br>", unsafe_allow_html=True)
        st.divider()
        st.markdown(
            "<div style='text-align:center;font-size:13px;color:#888;'>계정이 없으신가요?</div>",
            unsafe_allow_html=True,
        )
        _, btn_col, _ = st.columns([1, 2, 1])
        with btn_col:
            if st.button("📝 회원가입 신청", use_container_width=True):
                st.session_state.current_page = "register"
                st.rerun()


# ── 회원가입 신청 화면 ────────────────────────────────────────────────────────

def show_register_page():
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 📝 회원가입 신청")
        st.caption("관리자 승인 후 로그인이 가능합니다.")
        st.markdown("<br>", unsafe_allow_html=True)

        with st.form("register_form", clear_on_submit=True):
            username  = st.text_input("아이디", placeholder="영문·숫자·_·- 만 사용")
            name      = st.text_input("이름", placeholder="홍길동")
            password  = st.text_input("비밀번호 (6자 이상)", type="password")
            password2 = st.text_input("비밀번호 확인", type="password")
            submitted = st.form_submit_button("신청하기", type="primary", use_container_width=True)

        if submitted:
            username = username.strip()
            name     = name.strip()

            # 유효성 검사
            if not username or not name or not password:
                st.warning("⚠️ 모든 항목을 입력해 주세요.")
            elif not all(c.isalnum() or c in "_-" for c in username) or not username.isascii():
                st.warning("⚠️ 아이디는 영문·숫자·_·- 만 사용할 수 있습니다.")
            elif len(password) < 6:
                st.warning("⚠️ 비밀번호는 6자리 이상이어야 합니다.")
            elif password != password2:
                st.warning("⚠️ 비밀번호가 일치하지 않습니다.")
            elif username in _all_usernames():
                st.error("❌ 이미 사용 중인 아이디입니다. 다른 아이디를 입력해 주세요.")
            else:
                pending = load_json(PENDING_FILE)
                pending.append({
                    "username":     username,
                    "name":         name,
                    "password":     _hash_password(password),
                    "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                save_json(PENDING_FILE, pending)
                st.success(
                    "✅ 신청이 완료되었습니다!  \n"
                    "관리자 승인 후 로그인할 수 있습니다."
                )

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← 로그인으로 돌아가기", use_container_width=True):
            st.session_state.current_page = "login"
            st.rerun()


# ── 관리자 페이지 ─────────────────────────────────────────────────────────────

def show_admin_page():
    _render_sidebar_header()

    pending  = load_json(PENDING_FILE)
    approved = load_json(APPROVED_FILE)

    st.title("⚙️ 관리자 페이지")

    # ── 현황 카드 ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔔 승인 대기", len(pending))
    c2.metric("✅ 승인된 사용자", len(approved))
    c3.metric("👑 시스템 계정", len(_secrets_users()))
    c4.metric("👥 전체 사용자", len(approved) + len(_secrets_users()))

    st.divider()

    tab_pending, tab_approved, tab_system, tab_account = st.tabs(
        ["🔔 승인 대기", "✅ 승인된 사용자", "👑 시스템 계정", "🔧 계정 설정"]
    )

    # ── 탭 1: 승인 대기 ───────────────────────────────────────────────────────
    with tab_pending:
        if not pending:
            st.info("현재 승인 대기 중인 신청이 없습니다.")
        else:
            st.markdown(f"**총 {len(pending)}건**의 가입 신청이 대기 중입니다.")
            st.markdown("<br>", unsafe_allow_html=True)

            # 헤더
            h1, h2, h3, h4, h5 = st.columns([2, 2, 2, 1, 1])
            h1.markdown("**이름**")
            h2.markdown("**아이디**")
            h3.markdown("**신청일시**")
            h4.markdown("**승인**")
            h5.markdown("**거절**")
            st.divider()

            for user in list(pending):  # list() 로 복사해 순회 중 변경 방지
                col_name, col_id, col_date, col_ok, col_no = st.columns([2, 2, 2, 1, 1])
                col_name.write(user["name"])
                col_id.write(f"`{user['username']}`")
                col_date.write(user.get("requested_at", "-"))

                with col_ok:
                    if st.button("✅ 승인", key=f"approve_{user['username']}"):
                        new_approved = {
                            "username":    user["username"],
                            "name":        user["name"],
                            "password":    user["password"],
                            "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }
                        approved.append(new_approved)
                        pending = [u for u in pending if u["username"] != user["username"]]
                        save_json(PENDING_FILE, pending)
                        save_json(APPROVED_FILE, approved)
                        st.success(f"**{user['name']}** 님을 승인했습니다.")
                        st.rerun()

                with col_no:
                    if st.button("❌ 거절", key=f"reject_{user['username']}"):
                        pending = [u for u in pending if u["username"] != user["username"]]
                        save_json(PENDING_FILE, pending)
                        st.warning(f"**{user['name']}** 님의 신청을 거절했습니다.")
                        st.rerun()

    # ── 탭 2: 승인된 사용자 ───────────────────────────────────────────────────
    with tab_approved:
        if not approved:
            st.info("승인된 사용자가 없습니다.")
        else:
            st.markdown(f"**총 {len(approved)}명**의 사용자가 승인되어 있습니다.")
            st.markdown("<br>", unsafe_allow_html=True)

            h1, h2, h3, h4 = st.columns([2, 2, 3, 1])
            h1.markdown("**이름**")
            h2.markdown("**아이디**")
            h3.markdown("**승인일시**")
            h4.markdown("**삭제**")
            st.divider()

            for user in list(approved):
                c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
                c1.write(user["name"])
                c2.write(f"`{user['username']}`")
                c3.write(user.get("approved_at", "-"))
                with c4:
                    if st.button("🗑️", key=f"del_{user['username']}",
                                 help=f"{user['name']} 계정 삭제"):
                        approved = [u for u in approved if u["username"] != user["username"]]
                        save_json(APPROVED_FILE, approved)
                        st.success(f"**{user['name']}** 계정을 삭제했습니다.")
                        st.rerun()

    # ── 탭 4: 계정 설정 ───────────────────────────────────────────────────────
    with tab_account:
        cur_username = st.session_state.get("username", "")
        overrides    = _load_admin_overrides()
        cur_name     = (overrides.get(cur_username, {}).get("name")
                        or _secrets_users().get(cur_username, {}).get("name", cur_username))

        st.markdown(f"현재 로그인 계정: **`{cur_username}`** ({cur_name})")
        st.divider()

        # ── 표시 이름 변경 ────────────────────────────────────────────────────
        st.subheader("표시 이름 변경")
        with st.form("form_name"):
            new_name = st.text_input("새 표시 이름", value=cur_name)
            if st.form_submit_button("저장", type="primary"):
                if not new_name.strip():
                    st.warning("⚠️ 이름을 입력해 주세요.")
                else:
                    cur_pw_hash = (overrides.get(cur_username, {}).get("password")
                                   or _secrets_users().get(cur_username, {}).get("password", ""))
                    _save_admin_override(cur_username, new_name.strip(), cur_pw_hash)
                    st.session_state.display_name = new_name.strip()
                    st.success("✅ 표시 이름이 변경되었습니다.")
                    st.rerun()

        st.divider()

        # ── 비밀번호 변경 ─────────────────────────────────────────────────────
        st.subheader("비밀번호 변경")
        with st.form("form_pw"):
            cur_pw  = st.text_input("현재 비밀번호", type="password")
            new_pw  = st.text_input("새 비밀번호 (6자 이상)", type="password")
            new_pw2 = st.text_input("새 비밀번호 확인", type="password")
            if st.form_submit_button("변경", type="primary"):
                if not cur_pw or not new_pw or not new_pw2:
                    st.warning("⚠️ 모든 항목을 입력해 주세요.")
                elif len(new_pw) < 6:
                    st.warning("⚠️ 비밀번호는 6자리 이상이어야 합니다.")
                elif new_pw != new_pw2:
                    st.warning("⚠️ 새 비밀번호가 일치하지 않습니다.")
                else:
                    ok, _, _ = verify_login(cur_username, cur_pw)
                    if not ok:
                        st.error("❌ 현재 비밀번호가 올바르지 않습니다.")
                    else:
                        _save_admin_override(
                            cur_username, cur_name, _hash_password(new_pw)
                        )
                        st.success("✅ 비밀번호가 변경되었습니다. 다음 로그인부터 새 비밀번호를 사용하세요.")

    # ── 탭 3: 시스템 계정 (secrets.toml) ─────────────────────────────────────
    with tab_system:
        sec = _secrets_users()
        st.info(
            "시스템 계정은 `.streamlit/secrets.toml`에서 직접 관리합니다.  \n"
            "이 계정들은 자동으로 관리자 권한을 가집니다."
        )
        st.markdown("<br>", unsafe_allow_html=True)

        if not sec:
            st.warning("secrets.toml에 등록된 사용자가 없습니다.")
        else:
            h1, h2 = st.columns([3, 3])
            h1.markdown("**이름**")
            h2.markdown("**아이디**")
            st.divider()
            for uname, udata in sec.items():
                c1, c2 = st.columns([3, 3])
                c1.write(udata.get("name", uname))
                c2.write(f"`{uname}` 👑")


# ── TTS 메인 앱 ───────────────────────────────────────────────────────────────

def show_main_app():
    api_key = get_api_key()
    _render_sidebar_header()

    with st.sidebar:
        st.divider()

        if api_key == "__INVALID_KEY__":
            st.error(
                "⛔ **API 키 오류**: secrets.toml의 api_key에 한글 등 "
                "비ASCII 문자가 포함되어 있습니다.  \n"
                "실제 OpenAI API 키(`sk-...`)로 교체해 주세요."
            )
        elif not api_key:
            st.warning(
                "⚠️ **OpenAI API 키 미설정**  \n"
                "`.streamlit/secrets.toml`의 `api_key` 항목에 "
                "실제 키(`sk-...`)를 입력하세요."
            )

        st.subheader("🤖 모델 선택")
        model = st.selectbox("TTS 모델", options=MODELS, index=0)
        st.caption(f"ℹ️ {MODEL_DESCRIPTIONS[model]}")

        st.divider()

        st.subheader("🎤 음성 선택")
        if model == "gpt-4o-mini-tts":
            available_voices = VOICES_MINI_TTS
            voice_help = "cedar / marin이 최고 품질로 권장됩니다."
        else:
            available_voices = VOICES_LEGACY
            voice_help = f"{model} 지원 음성 9종"

        voice = st.selectbox(
            "Voice",
            options=available_voices,
            format_func=lambda v: f"{GENDER_EMOJI[VOICE_GENDER[v]]} {v}",
            help=voice_help,
        )

        g     = VOICE_GENDER[voice]
        badge = (
            f'<span style="background:{GENDER_BG[g]};color:{GENDER_FG[g]};'
            f'padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600;">'
            f'{GENDER_EMOJI[g]} {GENDER_LABEL[g]}</span>'
        )
        st.markdown(
            f'{badge} &nbsp;<span style="font-size:13px;color:#888;">'
            f'{VOICE_DESCRIPTIONS.get(voice, "")}</span>',
            unsafe_allow_html=True,
        )

        st.divider()
        st.caption("API 키는 서버에서만 사용되며 외부에 노출되지 않습니다.")

    # ── 메인 영역 ─────────────────────────────────────────────────────────────
    st.title("🎙️ OpenAI TTS 나레이션 생성기")
    st.markdown(
        "텍스트 대본을 입력하고 **음성 생성** 버튼을 누르면 OpenAI TTS API로 음성을 만들어 드립니다.  \n"
        "생성된 음성은 바로 들어보거나 **MP3 파일로 다운로드**할 수 있습니다."
    )
    st.divider()

    script = st.text_area(
        "📝 나레이션 대본",
        height=280,
        placeholder=(
            "여기에 음성으로 변환할 텍스트를 입력하세요.\n\n"
            "예) 안녕하세요. 오늘은 인공지능 음성 합성 기술에 대해 알아보겠습니다."
        ),
        help="OpenAI TTS는 한국어를 포함한 다국어를 지원합니다.",
    )

    instructions = ""
    if model == "gpt-4o-mini-tts":
        with st.expander("🎭 말투 / 감정 지시 (gpt-4o-mini-tts 전용)", expanded=False):
            st.markdown(
                "AI에게 말투·톤·속도·감정 등을 자연어로 지시할 수 있습니다.  \n"
                "비워두면 기본 스타일로 생성됩니다."
            )
            instructions = st.text_area(
                "지시 내용 (영문 권장)",
                height=100,
                placeholder=(
                    "예시:\n"
                    "- Speak slowly and warmly, like a friendly narrator.\n"
                    "- Use a cheerful and energetic tone.\n"
                    "- Whisper softly with a calm and soothing voice."
                ),
            )

    col_btn, _ = st.columns([1, 5])
    with col_btn:
        api_ready   = bool(api_key) and api_key != "__INVALID_KEY__"
        generate_btn = st.button(
            "🔊 음성 생성", type="primary",
            use_container_width=True, disabled=not api_ready,
        )

    st.divider()

    if generate_btn:
        # 버튼 비활성화 우회 시도에 대한 서버 측 이중 차단
        if not api_ready:
            st.error("⛔ 유효한 OpenAI API 키가 설정되지 않아 API 호출이 차단됩니다.")
            st.stop()

        if not script.strip():
            st.warning("⚠️ 나레이션 대본을 입력해 주세요.")
            st.stop()

        try:
            with st.spinner("🎵 음성을 생성하는 중입니다... 잠시만 기다려 주세요."):
                payload: dict = {"model": model, "voice": voice, "input": script.strip()}
                if model == "gpt-4o-mini-tts" and instructions.strip():
                    payload["instructions"] = instructions.strip()

                body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(
                        "https://api.openai.com/v1/audio/speech",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json; charset=utf-8",
                        },
                        content=body_bytes,
                    )

                if resp.status_code == 401:
                    st.error("❌ **API 키 인증 실패**: secrets.toml의 OpenAI API 키를 확인해 주세요.")
                    st.stop()
                elif resp.status_code == 429:
                    st.error("❌ **크레딧 한도 초과**: OpenAI 계정의 결제 정보 및 사용량을 확인해 주세요.")
                    st.stop()
                elif resp.status_code != 200:
                    err_msg = resp.json().get("error", {}).get("message", "알 수 없는 오류")
                    st.error(f"❌ **API 오류 ({resp.status_code})**: {err_msg}")
                    st.stop()

                audio_buffer = io.BytesIO(resp.content)
                audio_buffer.seek(0)

            st.success("✅ 음성 생성이 완료되었습니다!")
            st.subheader("🎧 미리 듣기")
            st.audio(audio_buffer, format="audio/mp3")

            audio_buffer.seek(0)
            st.download_button(
                label="⬇️ MP3 파일 다운로드",
                data=audio_buffer,
                file_name="narration.mp3",
                mime="audio/mpeg",
                type="secondary",
            )

        except httpx.ConnectError:
            st.error(
                "❌ **연결 오류**: OpenAI 서버에 접속하지 못했습니다.  \n"
                "인터넷 연결 상태를 확인하고 잠시 후 다시 시도해 주세요."
            )
        except httpx.TimeoutException:
            st.error("❌ **요청 시간 초과**: 네트워크가 느리거나 텍스트가 너무 깁니다.")
        except Exception as e:
            st.error(f"❌ **예기치 않은 오류**: {e}")


# ── 라우팅 ────────────────────────────────────────────────────────────────────
if not st.session_state.get("logged_in"):
    page = st.session_state.get("current_page", "login")
    if page == "register":
        show_register_page()
    else:
        show_login_page()
else:
    page = st.session_state.get("current_page", "tts")
    if page == "admin" and st.session_state.get("is_admin"):
        show_admin_page()
    else:
        show_main_app()
