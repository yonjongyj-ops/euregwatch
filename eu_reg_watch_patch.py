# =============================================================================
# eu_reg_watch.py 패치 — html_report 블록 교체
# =============================================================================
# 기존 코드에서 아래 블록을 찾아서 이 파일의 내용으로 교체하세요.
#
# [기존 블록 — 찾을 코드]
#
#     hr = cfg.get("html_report", {})
#     if hr.get("enabled") and not dry_run:
#         try:
#             from html_report import render_site
#             out_dir = hr.get("out_dir", "site")
#             paths = render_site(relevant_alerts, out_dir, cfg)
#             print(f"[info] HTML report written: {paths['index']} (+ archive)")
#         except Exception as e:
#             print(f"[warn] HTML report failed: {e}", file=sys.stderr)
#
# [교체할 코드 — 아래를 복사해서 붙여넣으세요]
# =============================================================================

    hr = cfg.get("html_report", {})
    if hr.get("enabled") and not dry_run:
        try:
            from html_report import render_site
            from html_report_patch import export_json, render_local_client

            out_dir = hr.get("out_dir", "site")

            # 기존 HTML 보고서 생성 (site/index.html + archive)
            paths = render_site(relevant_alerts, out_dir, cfg)
            print(f"[info] HTML report written: {paths['index']} (+ archive)")

            # [방법 A] alerts.json 내보내기
            # local_client.html 이 이 파일을 fetch 해서 렌더링합니다.
            export_json(relevant_alerts, out_dir)

            # [방법 A] local_client.html 생성 (github_raw_base 가 설정된 경우)
            # 최초 1회 생성 후 팀원에게 이 파일을 배포하면 됩니다.
            raw_base = hr.get("github_raw_base", "")
            if raw_base:
                lc_path = render_local_client(out_dir, raw_base)
                print(f"[info] local_client.html written: {lc_path}")

        except Exception as e:
            print(f"[warn] HTML report failed: {e}", file=sys.stderr)
