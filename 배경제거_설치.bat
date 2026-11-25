@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 먼저 "설치.bat"을 실행하세요.
  pause
  exit /b 1
)
echo 배경 제거 기능(rembg) 설치 중... 용량이 커서 오래 걸릴 수 있어요.
".venv\Scripts\python.exe" -m pip install "rembg[cpu]" || (echo [오류] 설치 실패. 파이썬 3.12/3.13을 권장합니다. & pause & exit /b 1)
echo.
echo 완료! 처음 배경 제거를 누를 때 모델(약 170MB)을 한 번 내려받아요.
pause
