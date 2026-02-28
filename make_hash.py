"""
비밀번호 해시 생성 유틸리티
───────────────────────────
사용법:
    python make_hash.py

pepper(.streamlit/secrets.toml의 auth.pepper 값)와
설정할 비밀번호를 입력하면 secrets.toml에 넣을 해시값을 출력합니다.
"""

import hashlib


def make_hash(password: str, pepper: str) -> str:
    return hashlib.sha256((password + pepper).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print("=" * 55)
    print("  OpenAI TTS 나레이션 생성기 - 비밀번호 해시 생성기")
    print("=" * 55)
    print()

    pepper = input("① secrets.toml의 [auth] pepper 값을 입력하세요:\n> ").strip()
    if not pepper:
        print("\n⚠️  pepper가 비어 있습니다. secrets.toml을 먼저 설정하세요.")
        raise SystemExit(1)

    print()
    password = input("② 설정할 비밀번호를 입력하세요:\n> ").strip()
    if not password:
        print("\n⚠️  비밀번호가 비어 있습니다.")
        raise SystemExit(1)

    result = make_hash(password, pepper)

    print()
    print("─" * 55)
    print("✅ 생성된 해시값 (아래 값을 secrets.toml의 password에 붙여넣으세요):")
    print()
    print(f"  {result}")
    print("─" * 55)
    print()
    print("예시 (secrets.toml):")
    print()
    print('  [users.admin]')
    print('  name     = "관리자"')
    print(f'  password = "{result}"')
    print()
