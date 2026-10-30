&lt;div align=&quot;center&quot;&gt;

# 🧴 코스메모 (CosMemo: Cosmetic + Memo)

"화장품을 사는 순간부터 다 쓰고 비울 때까지, 화장대의 기억을 대신 맡습니다."  
10~30대 여성의 화장품 생애주기(등록 → 분류·평가 → 기한·주의사항 안내 → 올바른 분리배출·폐기 → 다음 구매 전 체크)를 한 흐름으로 연결하는 백엔드 및 인터랙티브 웹 애플리케이션







**기초프로젝트랩 · 팀 오죠사마**

&lt;/div&gt;

## 1. 프로젝트 배경 및 문제 정의

화장품은 전자기기 등 내구재와 달리 구매 주기가 짧고(월 단위), 개봉 후 사용 기한(PAO)이 제품마다 다르며, 복합 재질 용기가 많아 분리배출이 어렵다는 특징이 있습니다. 실제 20대 여성 사용자 인터뷰를 통해 다음과 같은 4가지 핵심 페인 포인트(Pain Points)를 도출했습니다.

> - 방치되는 제품: *"세일 기간에 구매한 기초 제품이 피부 타입에 맞지 않아 방치 중이에요."*
> - 중복 소비 반복: *"매장에서 패키지가 예뻐서 샀는데 집에 이미 비슷한 색·종류의 제품이 있어서 안 써요."*
> - 기한 관리 부재: *"언제 땄는지 기억이 안 나서 몇 년씩 쓰는 제품도 있고, 기한이 지난 걸 쓴 적이 있는지조차 모르겠어요."*
> - 분리배출 혼란: *"다 쓴 화장품 용기는 분리수거가 안 될 것 같아서 그냥 일반쓰레기에 버려요."*

코스메모(CosMemo)는 구매 직후 영수증/수동 등록부터 개인 피부 궁합 기록, 개봉일 기반 사용 기한 관리, 부위별 용기 분리배출 안내, 그리고 다음 구매 전 중복·부적합 체크까지 **산 뒤의 전 과정을 끊김 없이 연결**합니다.

## 2. 기존 서비스와의 차별점

| 비교 항목 | 올리브영 | 화해 | 글로우픽 | 단순 기한 관리 앱 | 코스메모 (CosMemo) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 핵심 강점 | 구매, 피부 진단, 맞춤 추천 | 성분 리뷰, 내 사용템 궁합 점수 | 리뷰·랭킹 중심 탐색 | 단순 유통기한 알림 | 구매 후 전 과정 생애주기 연결 |
| 개봉일 + PAO 자동 계산 | 미제공 | 미제공 | 미제공 | 제공 | 제공 (인쇄기한과 비교해 더 이른 날 적용) |
| 비공개 개인 평가 이력 | 공개 리뷰 중심 | 공개 리뷰 중심 | 공개 리뷰 중심 | 미제공 | 기본 비공개 (시기별 평가 타임라인) |
| 구매 전 내 화장대 중복 체크 | 구매 내역 단순 조회 | 미제공 | 미제공 | 미제공 | 보유 잔량·기한·과거 부적합 기록 1:1 비교 |
| 부위별 분리배출 & 수거처 | 오프라인 캠페인 한정 | 미제공 | 미제공 | 미제공 | 본체·뚜껑·펌프 재질별 배출 가이드 & 수거함 안내 |

## 3. 핵심 기능 4단계 및 부가 기능

### 핵심 기능 4단계
1. 등록 (영수증 자동 인식 & 직접 등록)
   - 영수증(`R-031`) 촬영/업로드 시 화장품 품목만 자동 추출하고 비화장품(화장솜 등 소품)은 자동 제외합니다.
   - 카탈로그(`CAT-01~06`) 매칭으로 용량·주요 성분·기본 PAO를 채워주며, 개봉일이나 PAO를 모르는 경우 `'미등록'` 상태로 먼저 저장할 수 있습니다.
2. 분류 및 개인 평가 (비공개 타임라인)
   - 스킨케어·색조·향수 카테고리 및 주요 성분(`판테놀`, `병풀추출물`, `세라마이드 NP` 등)별로 내 화장대를 분류합니다.
   - 만족도(1~5점), 피부 궁합(`잘 맞아요` / `보통` / `맞지 않아요`), 피부 반응 태그, 재구매 의향을 **기본 비공개**로 기록하고 시기별 변화(`3.0 보통` → `4.0 잘 맞아요`)를 추적합니다.
3. 사용 기한 안내 (EXP-01 기한 계산 엔진)
   - 인쇄 사용 기한과 개봉일 + PAO(개봉 후 사용 기한) 두 가지를 모두 알면 더 이른 날짜를 최종 기한으로 자동 적용합니다.
   - 미개봉 제품은 개봉 전까지 PAO를 계산하지 않으며, 개봉일 등록(`PROD-03`) 즉시 기한과 알림(30일 전 / 7일 전 / 당일)을 재산출합니다.
4. 폐기 및 분리배출 안내 (삭제가 아닌 '지난 제품 보관함' 이동)
   - 사용 종료 사유(`다 썼어요`, `기한이 지났어요`, `피부에 맞지 않아요`)를 기록하고 본체(PP)·뚜껑(PP)·복합 라벨·금속 스프링 펌프 등 부위별 분리배출 방법과 지역 공병 수거처를 안내합니다.
   - 배출 완료 시 데이터를 삭제하지 않고 지난 제품 보관함(`ARC-01`)으로 옮겨 다음 소비를 위한 취향 기록으로 보존합니다.

### 부가 기능
- 구매 전 체크 (`BUY-01~02`): 구매를 고민 중인 제품 검색 시 내 화장대에 이미 보유 중인 동일/유사 제품(잔량 60%, 남은 기한)과 과거 맞지 않았던 제품(`시카 진정 젤 · 2.0 따가움`) 경고를 함께 제시하고 1:1 비교표를 제공합니다.
- 내 기록 기반 추천 (`REC-01`) & 계절별 케어 (`SEA-01`): 유행이나 광고보다 내 과거 만족도와 재구매 의향(`MY RECORD FIRST`)을 최우선으로 추천하며, 환절기 등 계절 변화에 맞춰 내가 보유한 보습 성분 제품을 안내합니다.
- 선택 공개 커뮤니티 (`COM-01~03`): 개인 평가는 철저히 비공개로 유지하되, 사용자가 원할 때만 체크박스로 선택한 항목(예: 한 줄 문구만 공개, 별점 제외)을 커뮤니티 게시글로 공유할 수 있습니다.
- 8대 예외 및 복구 설계 (`STATE-01~08`): 빈 화장대, 검색 결과 없음, 영수증 OCR 실패 시 초안 보존, 필수 브랜드 누락 부분 수정, 네트워크 오프라인 캐시 읽기 전용 모드, `idempotency_key` 기반 중복 저장 방지, 권한 거부 대체 경로, 세션 만료 시 작성 중이던 초안 자동 보관까지 완벽히 처리합니다.

## 4. 화면 설계도 (A ~ H) ↔ 백엔드 API 아키텍처 매핑

화면 설계도의 모든 화면 코드(`AUTH-01` ~ `STATE-08`)가 FastAPI 라우터와 1:1로 매핑되어 있습니다.

| 화면 그룹 | 화면 코드 | 엔드포인트 (Route) | 담당 라우터 및 주요 처리 내용 |
| :--- | :--- | :--- | :--- |
| **A · 시작 · 계정 만들기** | `AUTH-01` ~ `AUTH-06` | `GET /auth/welcome`<br>`POST /auth/signup`, `POST /auth/login`<br>`POST /auth/password-reset`<br>`PUT /auth/onboarding/skin`, `/permissions` | `app/routers/auth.py`<br>필수 약관 3종 검증, JWT 인증, 계정 존재 여부를 노출하지 않는 비밀번호 재설정, 피부 프로필 및 권한 온보딩 |
| **B · 홈 · 내 화장대 · 제품 관리** | `HOME-01`<br>`VAN-01` ~ `VAN-02`<br>`PROD-01` ~ `PROD-04` | `GET /home`<br>`GET /vanity`<br>`GET/PUT/DELETE /owned/{code}`<br>`POST /owned/{code}/open` | `app/routers/vanity.py`<br>대시보드 요약(활성 6 / 30일 이내 1 / 초과 1), 다중 필터링, 제품 상세·수정, 미개봉 개봉일 등록 및 기한 자동 재계산 |
| **C · 영수증에서 내 화장대로** | `REG-01` ~ `REG-08` | `POST /register/receipt/upload`<br>`GET/PUT /register/receipt/{code}/review`<br>`GET /register/catalog/match`<br>`GET /register/confirm`, `POST /register/manual` | `app/routers/register.py`<br>영수증(`R-031`) 파싱, 비화장품(`화장솜`) 제외, 카탈로그 매칭, 동일 보유 제품 중복 안내 후 화장대 반영 |
| **D · 개인 평가 · 사용 기한 · 알림** | `REV-01` ~ `REV-02`<br>`EXP-01`<br>`NOTI-01` | `GET /evaluations`<br>`POST /owned/{code}/evaluation`<br>`GET /deadlines`<br>`GET /notifications`, `POST /notifications/read-all` | `app/routers/evaluations.py`, `app/routers/me.py`<br>비공개 평가 타임라인, 기한 탭(`expired` / `within30` / `later` / `unknown`) 분류, 알림함 읽음 처리 |
| **E · 비우기 · 분리배출 · 다음 구매** | `DIS-01` ~ `DIS-04`<br>`ARC-01`<br>`BUY-01` ~ `BUY-02` | `POST /owned/{code}/end`<br>`GET /disposal/{code}/guide`, `POST .../complete`<br>`GET /collection`, `GET /archive`<br>`GET /precheck`, `GET /precheck/compare` | `app/routers/disposal.py`<br>종료 사유 기록, 부위별 분리배출 가이드, 공병 수거처 검색, 지난 제품 보관함 이동, 구매 전 1:1 비교 |
| **F · 추천 · 계절 케어 · 커뮤니티** | `REC-01`, `SEA-01`<br>`COM-01` ~ `COM-03` | `GET /recommendations`<br>`GET /seasonal/{season}`<br>`GET/POST/DELETE /community`<br>`POST /community/{code}/comments` | `app/routers/community.py`<br>내 기록 우선 추천, 가을 보습 루틴 가이드, 비공개 평가 선택 항목 공개 게시글 및 댓글 |
| **G · 마이 · 알림 환경 · 개인정보** | `MY-01` ~ `MY-03` | `GET /me`<br>`GET/PUT /me/notifications`<br>`PUT/DELETE /me/account`, `POST /me/logout` | `app/routers/me.py`<br>내 기록 통계, 기한 알림·마케팅 수신 분리 설정, 기기 로그아웃 및 `'탈퇴'` 문구 검증 후 영구 삭제 |
| **H · 공통 · 예외 상태** | `STATE-01` ~ `STATE-08` | 각 엔드포인트의 `state` / `simulate_state` 쿼리 파라미터 및 `GET /permissions` | 전 라우터 공통<br>빈 화면, 결과 없음, OCR 실패, 브랜드 누락, 오프라인 캐시, 중복 저장 방지, 권한 거부, 세션 만료 초안 보존 |

## 5. 폴더 구조 (Directory Structure)

```text
cosmemo-backend/
├── .gitignore                 # 가상환경(.venv), DB 파일(*.db), 환경변수(.env) 제외 설정
├── .env.example               # 환경변수 템플릿
├── requirements.txt           # FastAPI, SQLAlchemy, Pydantic 등 의존성 패키지
├── cosmemo_demo_app.html      # 화면 설계도(A~H) 100% 구현 인터랙티브 시연 웹앱
├── README.md                  # 프로젝트 소개 및 심사위원 시연 가이드
└── app/
    ├── __init__.py
    ├── config.py              # 프로젝트 환경 설정
    ├── database.py            # SQLAlchemy 엔진 및 DB 세션 관리
    ├── models.py              # 10개 핵심 엔티티 ORM 모델 (User, OwnedProduct, Evaluation 등)
    ├── schemas.py             # 요청/응답 데이터 검증 스키마
    ├── seed.py                # 시연 기준일(2026-10-30) 지윤님(USER-01) 초기 데이터 자동 시드
    ├── main.py                # FastAPI 엔트리포인트, CORS 설정 및 라우터 통합
    ├── utils/
    │   ├── __init__.py
    │   ├── deadline.py        # 인쇄 사용기한 vs 개봉일+PAO 비교 및 D-Day 계산 모듈
    │   └── security.py        # 비밀번호 해싱, JWT 토큰 및 세션 만료(STATE-08) 처리
    └── routers/
        ├── __init__.py
        ├── auth.py            # A · 시작 · 계정 만들기 (AUTH-01 ~ AUTH-06)
        ├── vanity.py          # B · 홈 · 내 화장대 · 제품 관리 (HOME-01, VAN-01~02, PROD-01~04)
        ├── register.py        # C · 영수증에서 내 화장대로 (REG-01 ~ REG-08)
        ├── evaluations.py     # D · 개인 평가 · 사용 기한 (REV-01~02, EXP-01)
        ├── disposal.py        # E · 비우기 · 분리배출 · 다음 구매 (DIS-01~04, ARC-01, BUY-01~02)
        ├── community.py       # F · 추천 · 계절 케어 · 커뮤니티 (REC-01, SEA-01, COM-01~03)
        └── me.py              # G · 마이 · 알림함 · 계정/권한 (NOTI-01, MY-01~03, STATE-07)
```

## 6. 빠른 시작 (Quick Start)

### 1) 가상환경 생성 및 패키지 설치

```bash
# Windows (PowerShell)
py -m venv .venv
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 백엔드 API 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

서버가 시작되면 `cosmemo.db`가 자동 생성되며, 화면 시안(기준일 `2026-10-30`)에 등장하는 **지윤님(`jiyun@example.com` / `cosmemo1234`)의 화장대 보유 제품 6개(`OWN-101~106`), 보관함 제품 2개(`OWN-098~099`), 영수증 초안(`R-031`), 평가 기록(`EVAL-100~104`), 공병 수거처(`COL-01~02`), 커뮤니티 게시글(`P-01~04`)**이 자동으로 입력됩니다.


## 7. 기대 효과 (Expected Impact)

- 고객 (User): 보유 제품과 과거 피부 궁합 기록을 바탕으로 불필요한 중복 구매와 후회를 줄이고, 사용 기한과 주의사항을 지켜 안전하게 화장품을 사용합니다.
- 사회 (ESG · Environment): 복합 재질 화장품 용기를 부위별로 올바르게 비우고 분리배출하는 문화를 확산하며, 브랜드 공병 수거함 및 리필 스테이션 참여를 촉진합니다.
- 서비스 (Platform): 새 화장품을 살 때와 다 쓰고 비울 때 모두 앱을 열어야 하는 명확한 반복 사용 동기를 제공하여, 기록이 쌓일수록 개인화 추천이 정교해지는 화장대 허브로 자리 잡습니다.
