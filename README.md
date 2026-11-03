# XRMemory Scene Graph

제어판의 공간 구성과 작업자의 관찰·판단·조작 기록을 연결하는 데이터 구조

## 구성

| 필드 | 내용 |
|---|---|
| `objects`, `relations` | 제어판·화면·영역·버튼과 포함·기능 관계 |
| `humans` | 작업자 ID와 숙련도 |
| `states`, `events` | 화면 상태 변화, 오류음, 버튼 조작 |
| `observations`, `interpretation` | 관찰한 단서와 판단 이유 |
| `decision_graph` | 판단 지점(DP1~DP5)과 갱신 기록 |
| `metadata` | 버전, 시간 기준, 좌표계 |

## 데이터 예시

| 파일 | 내용 |
|---|---|
| [p4_cutting_error.json](examples/p4_cutting_error.json) | 공간 기록과 Decision Graph를 연결한 예시 |
| [p4_cutting_error.source.json](examples/p4_cutting_error.source.json) | 공간 그래프 원본 예시 |
| [dp5_underreaction.synthetic.json](examples/dp5_underreaction.synthetic.json) | 이상이 악화돼도 절단을 유지하는 합성 입력 |
| [dp5_underreaction.expected.json](examples/dp5_underreaction.expected.json) | 합성 입력의 예상 출력 |
| [decision-design.source.json](config/decision-design.source.json) | Decision 구조·규칙 원문 |
