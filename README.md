# 🎙️ OpenAI TTS 나레이션 생성기

OpenAI TTS API를 활용하여 텍스트 대본을 MP3 음성 파일로 변환하는 Streamlit 웹 애플리케이션입니다.

## 주요 기능

- **API 키 직접 입력**: 사용자가 자신의 OpenAI API 키를 사이드바에 입력하여 사용 (서버 저장 없음)
- **모델 선택**: `tts-1` (빠른 응답) / `tts-1-hd` (고품질)
- **6가지 음성**: alloy, echo, fable, onyx, nova, shimmer
- **실시간 미리 듣기**: 생성된 음성을 브라우저에서 즉시 재생
- **MP3 다운로드**: 생성된 파일을 로컬에 저장

## 로컬 실행 방법

```bash
# 1. 패키지 설치
pip install -r requirements.txt

# 2. 앱 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 로 접속합니다.

## Streamlit Community Cloud 배포

1. 이 저장소를 GitHub에 Push
2. [share.streamlit.io](https://share.streamlit.io) 에서 **New app** 클릭
3. 저장소와 `app.py` 를 선택 후 배포
4. 배포 후 사이드바에서 각자의 API 키를 입력하여 사용

> **보안**: API 키는 코드 및 환경 변수에 저장되지 않으며 세션 내에서만 사용됩니다.

## 파일 구조

```
GPT TTS/
├── app.py            # 메인 Streamlit 애플리케이션
├── requirements.txt  # Python 패키지 의존성
└── README.md         # 프로젝트 안내서
```
