#!/usr/bin/env python3
"""수집 결과(또는 실패 알림)를 이메일로 발송. 설정은 모두 환경변수(GitHub Secrets)에서 읽는다.

필수: SMTP_HOST, SMTP_USER, SMTP_PASS, MAIL_TO
선택: SMTP_PORT(기본 465), MAIL_FROM(기본 SMTP_USER), MAIL_ATTACH(1=결과 파일 첨부, 0=요약만; 기본 1)
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path


def need(name):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"환경변수 {name} 가 설정되지 않았습니다.")
    return v


def run_url():
    s, r, i = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{s}/{r}/actions/runs/{i}" if s and r and i else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["success", "failure"], required=True)
    ap.add_argument("--result", default="result")
    args = ap.parse_args()

    host, user, pw, to = need("SMTP_HOST"), need("SMTP_USER"), need("SMTP_PASS"), need("MAIL_TO")
    port = int(os.environ.get("SMTP_PORT", "465"))
    sender = os.environ.get("MAIL_FROM", user)
    attach = os.environ.get("MAIL_ATTACH", "1") == "1"

    msg = EmailMessage()
    msg["From"], msg["To"] = sender, to

    if args.mode == "success":
        data = json.loads(Path(f"{args.result}.json").read_text(encoding="utf-8"))
        n = len(data["rows"])
        msg["Subject"] = f"[FINES] 민원자료공유 수집 완료 ({n}건)"
        body = [f"수집 건수: {n}건", f"컬럼: {', '.join(data['headers'])}"]
        if attach:
            body.append("결과 파일을 첨부했습니다.")
            for ext, mt in (("csv", ("text", "csv")), ("json", ("application", "json"))):
                p = Path(f"{args.result}.{ext}")
                if p.exists():
                    msg.add_attachment(p.read_bytes(), maintype=mt[0], subtype=mt[1], filename=p.name)
        else:
            body.append("(MAIL_ATTACH=0 설정: 요약만 발송)")
    else:
        msg["Subject"] = "[FINES] 민원자료공유 수집 실패"
        body = ["수집 중 오류가 발생했습니다.", "로그 확인: " + (run_url() or "(GitHub Actions 실행 로그)")]

    if run_url():
        body.append(f"실행 로그: {run_url()}")
    msg.set_content("\n".join(body))

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, pw)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
    print("메일 발송 완료")


if __name__ == "__main__":
    main()
