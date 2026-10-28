#!/usr/bin/env python3
"""
FINES(금융감독원) 민원자료공유 목록 스크래퍼 (Playwright 기반)

로컬 수동 로그인:   python fss_scraper.py --out result
로컬 로그인화면 저장: python fss_scraper.py --dump-login      (ID/PW 입력 없음)
무인 실행(CI):      FINES_ID / FINES_PW 환경변수 + python fss_scraper.py --ci --out result

환경변수(선택): FINES_ID_SEL, FINES_PW_SEL, FINES_LOGIN_BTN_SEL  → 로그인 입력창 CSS 선택자 직접 지정
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://fines.fss.or.kr/index.jsp"
TARGET_URL = (
    "https://fines.fss.or.kr/fines/ahp/home/index.jsp?url="
    "&sub_menu_title=%EB%AF%BC%EC%9B%90%EC%9E%90%EB%A3%8C%EA%B3%B5%EC%9C%A0"
    "&main_menu_title=%EB%AF%BC%EC%9B%90%EC%9E%90%EB%A3%8C%EA%B3%B5%EC%9C%A0"
    "&menuID=F070000&reportChk=R&gubn=1"
)
STATE_FILE = Path("fines_state.json")

JS_LIST_TABLES = """
() => [...document.querySelectorAll('table')].map((t, i) => ({
    idx: i,
    nested: !!t.querySelector('table'),
    rows: t.rows.length
}))
"""

JS_EXTRACT = """
(idx) => {
  const t = document.querySelectorAll('table')[idx];
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const rows = [...t.rows];
  if (!rows.length) return {headers: [], rows: []};
  const headers = [...rows[0].cells].map(c => clean(c.innerText));
  const data = rows.slice(1).map(r => {
    const cells = [...r.cells].map(c => clean(c.innerText));
    const a = r.querySelector('a');
    const link = a ? (a.getAttribute('href') || '') + ' ' + (a.getAttribute('onclick') || '') : '';
    return {cells, link: clean(link)};
  }).filter(r => r.cells.length >= 2);
  return {headers, rows: data};
}
"""


def log(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- 로그인
def open_target(page, state):
    """대상 페이지를 열고, 로그인된 상태면 True."""
    state["logged_out"] = False
    page.goto(TARGET_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if state["logged_out"] or urlparse(page.url).path == "/index.jsp":
        return False
    return True


def _find_visible(page, selectors, frames=None):
    for fr in frames or page.frames:
        for sel in selectors:
            try:
                loc = fr.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return fr, loc.first
            except Exception:
                continue
    return None, None


def auto_login(page, uid, pw):
    """ID/PW 자동 입력. 비밀번호는 로그에 출력하지 않는다."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    pw_sel = [os.environ["FINES_PW_SEL"]] if os.environ.get("FINES_PW_SEL") else ['input[type="password"]']
    fr, pw_box = _find_visible(page, pw_sel)
    if pw_box is None:
        raise RuntimeError("비밀번호 입력창을 찾지 못했습니다. --dump-login 으로 구조를 확인하고 FINES_PW_SEL 을 지정하세요.")

    id_sel = [os.environ["FINES_ID_SEL"]] if os.environ.get("FINES_ID_SEL") else [
        'input[type="text"][name*="id" i]',
        'input[type="text"][id*="id" i]',
        'input[type="text"]',
    ]
    _, id_box = _find_visible(page, id_sel, frames=[fr])
    if id_box is None:
        raise RuntimeError("아이디 입력창을 찾지 못했습니다. FINES_ID_SEL 을 지정하세요.")

    id_box.fill(uid)
    pw_box.fill(pw)

    btn_sel = [os.environ["FINES_LOGIN_BTN_SEL"]] if os.environ.get("FINES_LOGIN_BTN_SEL") else [
        'input[type="submit"]',
        'button[type="submit"]',
        'button:has-text("로그인")',
        'a:has-text("로그인")',
        'input[alt*="로그인"]',
        'img[alt*="로그인"]',
    ]
    _, btn = _find_visible(page, btn_sel, frames=[fr])
    if btn is not None:
        btn.click()
    else:
        pw_box.press("Enter")
    page.wait_for_timeout(3000)


def ensure_login(ctx, page, ci):
    state = {"logged_out": False}

    def on_dialog(d):
        if "로그인" in d.message:
            state["logged_out"] = True
        d.accept()

    page.on("dialog", on_dialog)

    if open_target(page, state):
        return

    uid, pw = os.environ.get("FINES_ID"), os.environ.get("FINES_PW")
    if uid and pw:
        log("자동 로그인을 시도합니다.")
        auto_login(page, uid, pw)
        ctx.storage_state(path=str(STATE_FILE))
        if not open_target(page, state):
            raise RuntimeError(
                "로그인에 실패했습니다. (아이디/비밀번호 오류, 추가 인증(OTP·인증서), "
                "보안키패드, 또는 해외 IP 차단 가능성)"
            )
        return

    if ci:
        raise RuntimeError("FINES_ID / FINES_PW 환경변수(Secrets)가 설정되지 않았습니다.")

    log("로그인이 필요합니다. 열린 브라우저 창에서 로그인하세요.")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    input("로그인을 마친 뒤 이 터미널에서 Enter를 누르세요... ")
    ctx.storage_state(path=str(STATE_FILE))
    if not open_target(page, state):
        raise RuntimeError("로그인이 확인되지 않았습니다.")


# ---------------------------------------------------------------- 수집
def find_data_frame(page):
    best = None
    for fr in page.frames:
        try:
            tables = fr.evaluate(JS_LIST_TABLES)
        except Exception:
            continue
        for t in tables:
            if t["nested"]:
                continue
            if best is None or t["rows"] > best[2]:
                best = (fr, t["idx"], t["rows"])
    return best


def dump(page, outdir):
    d = Path(outdir)
    d.mkdir(exist_ok=True)
    for i, fr in enumerate(page.frames):
        try:
            (d / f"frame_{i}.html").write_text(fr.content(), encoding="utf-8")
            log(f"저장: {d}/frame_{i}.html  ({fr.url})")
        except Exception as e:
            log(f"frame_{i} 저장 실패: {e}")
    try:
        page.screenshot(path=str(d / "page.png"), full_page=True)
    except Exception:
        pass
    log(f"완료: {d.resolve()}  (개인정보가 있으면 가린 뒤 공유하세요)")


def go_next(page, fr, cur_page, next_selector):
    candidates = []
    if next_selector:
        candidates.append(next_selector)
    candidates += [
        f'a:text-is("{cur_page + 1}")',
        'a:has-text("다음")',
        'a[title*="다음"]',
        'a:has-text("Next")',
    ]
    for sel in candidates:
        loc = fr.locator(sel)
        if loc.count() > 0:
            try:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1200)
                return True
            except Exception:
                continue
    return False


def scrape(page, max_pages, next_selector):
    if not find_data_frame(page):
        raise RuntimeError("데이터 표를 찾지 못했습니다. 로그인 후 화면 구조 확인이 필요합니다.")
    all_rows, headers, prev_sig = [], None, None

    for n in range(1, max_pages + 1):
        found = find_data_frame(page)
        if not found:
            break
        fr, idx, _ = found
        data = fr.evaluate(JS_EXTRACT, idx)
        headers = headers or data["headers"]
        sig = json.dumps(data["rows"][:3], ensure_ascii=False)
        if sig == prev_sig:
            break
        prev_sig = sig
        for r in data["rows"]:
            all_rows.append({"page": n, "cells": r["cells"], "link": r["link"]})
        log(f"{n}페이지: {len(data['rows'])}건 (누적 {len(all_rows)})")
        if not go_next(page, fr, n, next_selector):
            break
    return headers or [], all_rows


def save(headers, rows, out):
    with open(f"{out}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["page"] + headers + ["link"])
        for r in rows:
            w.writerow([r["page"]] + r["cells"] + [r["link"]])
    with open(f"{out}.json", "w", encoding="utf-8") as f:
        json.dump({"headers": headers, "rows": rows}, f, ensure_ascii=False, indent=2)
    log(f"저장 완료: {out}.csv, {out}.json ({len(rows)}건)")


def main():
    ap = argparse.ArgumentParser(description="FINES 민원자료공유 스크래퍼")
    ap.add_argument("--out", default="result", help="출력 파일명(확장자 제외)")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--next-selector", help="'다음' 버튼 CSS 선택자")
    ap.add_argument("--dump", action="store_true", help="로그인 후 목록 화면 HTML 저장 후 종료")
    ap.add_argument("--dump-login", action="store_true", help="로그인 화면만 저장 후 종료(ID/PW 불필요)")
    ap.add_argument("--dump-on-error", action="store_true", help="오류 시 화면 HTML 저장(개인정보 주의)")
    ap.add_argument("--relogin", action="store_true", help="저장된 세션 무시")
    ap.add_argument("--ci", action="store_true", help="무인 실행: 헤드리스, 입력 대기 없음")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.ci or args.dump_login)
        kw = {"locale": "ko-KR", "timezone_id": "Asia/Seoul"}
        if STATE_FILE.exists() and not args.relogin:
            kw["storage_state"] = str(STATE_FILE)
        ctx = browser.new_context(**kw)
        page = ctx.new_page()

        try:
            if args.dump_login:
                page.goto(LOGIN_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                dump(page, "dump_login")
                return

            ensure_login(ctx, page, args.ci)
            if not args.ci:
                input("조회 조건(기간 등)을 설정하고 목록이 보이면 Enter를 누르세요... ")

            if args.dump:
                dump(page, "dump")
            else:
                headers, rows = scrape(page, args.max_pages, args.next_selector)
                save(headers, rows, args.out)
        except Exception as e:
            log(f"오류: {e}")
            if args.dump_on_error:
                dump(page, "dump_error")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
