# CLAUDE.md

## 브랜치 네이밍 규칙

브랜치 생성 시 반드시 아래 형식을 따를 것:

```
claude/kebab-description-N
```

| 항목 | 규칙 |
|---|---|
| `claude/` | 고정 prefix, 절대 생략 금지 |
| `kebab-description` | 2~5단어, 소문자, 하이픈 구분 |
| `-N` | 기존 `claude/` 브랜치 최대 번호 + 1 |

**예시**
```
claude/fix-login-bug-1
claude/add-toto-feature-2
claude/refactor-db-layer-3
```

**브랜치 생성 절차**
1. `git branch -a | grep 'claude/'` 로 기존 번호 확인
2. 최대 번호 + 1 을 N으로 사용 (없으면 N=1)
3. `git checkout -b claude/your-slug-N`
4. 랜덤 문자열(예: `claude/beautiful-hopper-FvyrU`) 절대 사용 금지

---

## 코드 작성 규칙

- 기본 언어: **Python** (별도 지시 없을 시)
- 성능 최적화 최우선, 가독성 유지
- 변수명: `camelCase`
- 코드 블록마다 역할 주석 필수
- 예외 처리 필수

---

## 커밋 메시지 규칙

```
<type>: <short description>
```

| type | 용도 |
|---|---|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 |
| `docs` | 문서 수정 |
| `chore` | 설정, 의존성 등 |

---

## 작업 원칙

- 구현 전 반드시 설계 방향 먼저 확인
- 파일 수정 전 기존 코드 파악 후 진행
- 큰 변경사항은 단계별로 나눠서 진행
