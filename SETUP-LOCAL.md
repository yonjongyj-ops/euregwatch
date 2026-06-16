# 로컬 PC 실시간 업데이트 — 설정 가이드

팀원이 **로컬 PC에 파일을 가지고 있으면서** 열 때마다 최신 내용을 보는 방법입니다.

---

## 방법 A — 로컬 HTML이 GitHub에서 자동 fetch (권장)

### 동작 원리

```
매일 07:00 UTC
  Actions 실행
    → alerts.json 생성 → site/ 에 커밋
    → (GitHub Pages or raw URL 로 공개)

팀원이 local_client.html 을 더블클릭
    → JS가 raw.githubusercontent.com/site/alerts.json fetch
    → 최신 데이터로 카드 렌더링
    → 항상 오늘 아침 기준 최신본 표시
```

### 설정 방법 (15분)

**1. config.yaml 수정**

```yaml
html_report:
  enabled: true
  out_dir: "site"
  github_raw_base: "https://raw.githubusercontent.com/yourname/eu-reg-watch/main/site"
  #                                                    ^^^^^^^^  ^^^^^^^^^^^^
  #                                                    GitHub 유저명  repo 이름
```

**2. 파일 추가**

repo 루트에 아래 두 파일을 올립니다.
- `html_report_patch.py`
- `watch.yml` (기존 파일 교체)

`eu_reg_watch.py` 에서 html_report 블록을 `eu_reg_watch_patch.py` 의 내용으로 교체합니다.

**3. Actions 실행**

Actions 탭 → Run workflow → 실행이 끝나면 `site/local_client.html` 이 생성됩니다.

**4. 팀원에게 배포**

`site/local_client.html` 파일을 팀원에게 한 번만 전달합니다.
- 이메일 첨부, Slack 파일 공유, 사내 공유 폴더 어디든 가능
- **이후로는 배포 불필요** — 파일을 열 때마다 자동으로 최신 데이터를 가져옵니다.

### 전제 조건

| 조건 | 내용 |
|------|------|
| 인터넷 연결 | 파일을 열 때 필요 (오프라인 불가) |
| repo 공개 여부 | **Public repo** 여야 raw URL 이 무료로 열림 |
| Private repo 대안 | GitHub Pages 활성화 시 Pages URL 로 대체 가능 |

> Private repo + GitHub Pages: Settings → Pages → Source: main / /site 로 설정하면
> `github_raw_base` 대신 `https://yourname.github.io/eu-reg-watch` 를 사용할 수 있습니다.
> 단, Pages URL 은 CDN 캐시가 있어 반영까지 최대 10분 걸릴 수 있습니다.

---

## 방법 B — Actions가 이메일로 최신 HTML 자동 발송

### 동작 원리

```
매일 07:00 UTC
  Actions 실행
    → site/index.html 생성
    → SendGrid API 로 이메일 발송
    → 수신자가 첨부 파일을 저장 후 열기
```

### 설정 방법 (20분)

**1. SendGrid 계정 생성 (무료)**

1. https://sendgrid.com 가입
2. Settings → Sender Authentication → 발신 주소 인증
3. Settings → API Keys → Create API Key
   - 이름: `eu-reg-watch`
   - 권한: `Mail Send` 만 체크
   - 생성된 키 복사 (SG.xxx...)

**2. GitHub Secrets 추가**

repo → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|-------------|-----|
| `SENDGRID_API_KEY` | SendGrid API 키 |
| `MAIL_TO` | `user1@company.com,user2@company.com` |
| `MAIL_FROM` | SendGrid 에서 인증한 발신 주소 |

**3. 파일 추가**

repo 루트에 `watch.yml` 을 교체합니다 (이메일 발송 스텝이 포함되어 있습니다).

**4. 테스트**

Actions → Run workflow → 이메일 수신 확인

### 장단점

| 항목 | 내용 |
|------|------|
| 인터넷 | 이메일만 되면 됨 (오프라인 열람 가능) |
| 최신성 | 이메일 수신 = 그날 최신본. 재열람 시 업데이트 없음 |
| 번거로움 | 매번 첨부 파일 저장 필요 |
| 비용 | SendGrid 무료 플랜 월 100건 (하루 1건 × 30일 = 30건) |

---

## 두 방법 비교

| | 방법 A (fetch) | 방법 B (이메일) |
|--|---------------|----------------|
| 파일 배포 | 최초 1회만 | 매일 이메일 |
| 오프라인 | 불가 | 가능 |
| 항상 최신 | 열 때마다 | 수신 시점만 |
| 설정 난이도 | 쉬움 | 보통 |
| 추천 상황 | 일반 사용 | 오프라인 환경 |

**결론**: 방법 A를 기본으로 쓰고, 출장·오프라인 환경이 많은 팀원에게만 방법 B를 병행하는 것이 좋습니다.
두 방법은 동시에 활성화할 수 있습니다 (`watch.yml` 에 두 스텝이 모두 포함되어 있습니다).
