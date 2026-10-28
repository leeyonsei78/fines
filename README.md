# FINES 민원자료공유 수집 → 이메일 발송

GitHub Actions에서 FINES에 로그인해 목록을 수집하고 결과를 이메일로 보냅니다.

## 0. 먼저 읽어 주세요
- **저장소는 반드시 Private**으로 만드세요. 민원 자료에는 개인정보가 포함될 수 있습니다.
- GitHub 호스티드 러너는 해외(미국) IP입니다. FINES가 해외 IP·비인가 IP를 막으면 로그인이 실패합니다.
  이 경우 국내 PC/서버에 **self-hosted runner**를 설치하고 workflow의 `runs-on`을 `self-hosted`로 바꾸세요.
- 사이트에 OTP·인증서·보안키패드가 있으면 ID/PW만으로는 로그인되지 않을 수 있습니다.
- 결과 파일을 메일로 보내면 사내 메일 시스템에 개인정보가 남습니다. 부담되면 `MAIL_ATTACH=0`(요약만 발송)로 시작하세요.

## 1. 저장소 만들고 올리기
```bash
cd fines-scraper
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin https://github.com/<계정>/<저장소>.git   # Private 저장소
git push -u origin main
```

## 2. Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret

| 이름 | 설명 |
|---|---|
| `FINES_ID` / `FINES_PW` | FINES 로그인 (RPA 전용 계정 권장) |
| `SMTP_HOST` | 예: `smtp.gmail.com` |
| `SMTP_PORT` | 465 (SSL) 또는 587 (STARTTLS). 비우면 465 |
| `SMTP_USER` / `SMTP_PASS` | 발송 계정 / 비밀번호. Gmail은 2단계 인증 후 **앱 비밀번호** 사용 |
| `MAIL_TO` | 받는 사람 (쉼표로 여러 명) |
| `MAIL_FROM` | (선택) 보내는 사람 표시 |
| `MAIL_ATTACH` | (선택) `1`=CSV/JSON 첨부, `0`=요약만 |
| `FINES_ID_SEL` `FINES_PW_SEL` `FINES_LOGIN_BTN_SEL` | (선택) 자동 로그인이 입력창을 못 찾을 때 CSS 선택자 지정 |

## 3. 테스트
1. Actions 탭 → **FINES scrape** → **Run workflow** (처음엔 `debug` 체크)
2. 성공하면 메일이 도착합니다. 실패해도 "수집 실패" 메일과 실행 로그 링크가 옵니다.
3. 입력창을 못 찾는다는 오류가 나면, 로컬에서 `python fss_scraper.py --dump-login` 으로 `dump_login/`을 만들어 구조를 확인하세요(ID/PW 입력 없음).
4. 정상 동작을 확인한 뒤 `debug`를 끄세요. 디버그 덤프에는 화면 내용이 들어갑니다.

## 로컬 테스트
```bash
pip install -r requirements.txt && playwright install chromium
python fss_scraper.py --out result          # 브라우저에서 직접 로그인
FINES_ID=... FINES_PW=... python fss_scraper.py --ci --out result   # 자동 로그인 확인
```
