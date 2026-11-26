# FM Face Studio

Football Manager 27의 선수·스태프·지원 스태프·내 감독 얼굴 사진을 바꾸는 Windows 프로그램이에요.
A Windows tool to replace player, staff and manager portraits in Football Manager 27.

## 기능
- 세이브를 읽어 선수·스태프를 이름·팀으로 찾고, 지금 쓰이는 사진을 카드로 보여 줘요 (뉴젠 포함)
- 사진 편집기: 자르기·확대, 얼굴 자동 맞춤, 배경 제거, 이름 넣기·둥근 모서리·테두리
- AI 사진 만들기: 제미나이·그록·챗GPT 웹(무료) 또는 API 키로 새 얼굴·유니폼만 바꾸기
- 대기열에 모아 한 번에 적용 (`graphics\zzz_FMFaceStudio` 폴더와 `config.xml` 자동 관리 — FM은 이름순으로 뒤 폴더가 이기므로 맨 뒤 이름을 써요)
- BepInEx 플러그인(선택): 게임을 끄지 않고 바로 반영, 내 감독 사진 바꾸기, 게임 외모 정보 읽기

## 받기
[Releases](../../releases)에서 `FMFaceStudio-Setup.exe`를 받아 설치하세요. 파이썬 설치는 필요 없어요. 설치한 뒤에는 새 버전이 나오면 프로그램이 알려 주고 버튼 한 번으로 업데이트돼요.
처음 실행할 때 파란 "Windows의 PC 보호" 창이 뜨면 "추가 정보" → "실행"을 누르세요.

## Privacy policy
This program will not transfer any information about you to other networked systems unless specifically requested by the user:
- **AI image generation** — only when you press the AI button, the prompt (and the photos you chose to attach) are sent to the AI service you selected (Google Gemini, xAI Grok, OpenAI, Cloudflare). Their own privacy policies apply. The "web" options only open the site in your browser and copy to your clipboard.
- **Update check** — at start-up the program asks the GitHub API (`api.github.com`) for the latest release version of this repository. No personal data is sent. It can be turned off in Settings → Update. Updates are downloaded from this repository's GitHub releases only when you press the update button.
- **Background-removal model** — downloaded once from GitHub when you first use background removal.

The program reads your Football Manager save and graphics folders on your own computer only. Settings and logs stay in `%APPDATA%\FM27FacePicker`. The "error report" file is created on your desktop and is never sent automatically.

## License
[MIT](LICENSE). Third-party components are listed in [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
