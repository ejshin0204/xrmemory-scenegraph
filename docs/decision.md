# Decision Graph

HTML의 DecisionPoint 5개와 NEXT / UPDATE 구조를 반영합니다. 물리 객체의 relations와 분리된 `decision_graph`에 저장합니다. 각 그래프는 한 trial의 한 actor에 속합니다.

## 판단 지점

| ID | 의미 | 요구 상태 | 목표 상태 |
|---|---|---|---|
| DP1 | 시스템 활성화 | S0 | S1 |
| DP2 | 조건 로드 | S1 | S2 |
| DP3 | 예열 개시 | S2 | S3 |
| DP4 | 절단 개시 | S3 | S4 |
| DP5 | 절단 중 이상 감지 및 대응 판단 | S4 | S4 |

S0 시스템 비활성, S1 시스템 활성, S2 조건 로드 완료, S3 예열, S4 절단입니다. 이는 제공 HTML의 예제용 상태 체계입니다. DP4는 천공·자동절단 버튼을 한 판단 단계로 묶은 것으로 버튼 하나와 일대일 대응하지 않습니다.

## 에지와 기록

- NEXT는 절차 순서를 나타내며 실제 수행 완료를 뜻하지 않습니다.
- UPDATE는 이전 기록의 DP에서 현재 기록의 DP로 연결합니다. 동일 source/target이면 records에 누적하며 같은 DP 내부 갱신은 self-loop입니다.
- 첫 기록은 본 패키지에서 해당 DP self-loop에 저장합니다.
- `previous_event_id`는 **이전 UPDATE 기록 ID**입니다. 공간 기록의 event_01과 혼동하지 않습니다.
- `latest_event_id`는 해당 DP의 최신 UPDATE 기록 ID입니다. 기록이 없으면 null이고 상태와 Belief는 UNKNOWN입니다.

| UPDATE.records 필드 | 의미 |
|---|---|
| id / time_ms / previous_event_id | 갱신 기록 ID, 공통 시간, 이전 기록 |
| task_state | 해당 시점 작업 상태 |
| observation.evidence_refs | 통합 JSON 내부 근거를 가리키는 JSON Pointer |
| inference.expert_severity | 별도 기준에 따른 위험 평가 |
| inference.user_state / status | 사용자 상태 추정과 근거 상태 |
| inference.belief | 사용자가 판단했을 위험도의 후보·출처·가설 |
| inference.primary_rule / matched_rules | 대표 규칙과 일치 규칙 전체 |

## 보고와 추정 구분

`interpretation.severity`는 작업자의 직접 보고입니다. 숙련자의 보고라도 독립적으로 정한 `expert_severity`와 자동으로 같게 두지 않습니다.

Belief의 source는 SELF_REPORT, BEHAVIORAL_HYPOTHESES, WEAK_BEHAVIORAL_EVIDENCE, INSUFFICIENT_EVIDENCE 중 하나입니다. UNKNOWN은 별도의 위험 등급이 아니라 판단을 알 수 없다는 표시입니다. 가설 ID는 확률이나 순위가 아닙니다.

통합 예시에서는 12.1초 HIGH 보고를 SELF_REPORT로 연결합니다. 이후 기록은 마지막 보고를 유지하지만, 새로 판단했다고 주장하지 않습니다. expert_severity와 user_state는 UNKNOWN, status는 INSUFFICIENT_EVIDENCE로 둡니다. status의 이 값은 본 패키지에서 추가한 표기입니다.

## 규칙 (HTML의 예제용 정의)

| ID | 조건 | 결과 | 우선순위 |
|---|---|---|---|
| R1 | 정상 버튼 선택 AND 상태 전이 성공 | Normal Execution | 60 |
| R2 | 관련 단서 응시 AND 정답 대상에 손 접근 | Active Reasoning | 40 |
| R3 | 버튼 간 시선·손 왕복 ≥ 3 AND 손이 여러 조작부 사이에 위치 | Hesitation | 70 |
| R4 | 관련 대상 탐색 실패 AND 진전 없음 ≥ 10초 | Stuck | 80 |
| R5 | DP5 AND 전문가 기준 HIGH AND PAUSE/STOP/EMERGENCY_STOP 미수행 | Underreaction | 100 |
| R6 | DP5 AND 전문가 기준 LOW AND EMERGENCY_STOP | Overreaction | 90 |
| R7 | DP5 AND 이상음 누적 ≥ 2 AND 기준 MID AND 관련 단서 응시 AND CONTINUE/OBSERVE | Monitoring | 50 |
| R8 | DP5 AND 전문가 기준 HIGH AND PAUSE/STOP/EMERGENCY_STOP | Normal Execution | 95 |

동시에 일치하면 우선순위가 가장 높은 규칙이 대표가 되고 나머지도 보존합니다. HTML의 합성 위험도 기준은 이상음 2회 이상·불꽃 악화·절단 결과 악화가 함께 있으면 HIGH, 이상 단서가 있으나 결합 조건 미충족이면 MID, 이상음 0회·불꽃 정상·절단 결과 정상이면 LOW, 판단 근거 부족이면 UNKNOWN입니다.

**이 기준은 검증된 안전 기준이나 사용자 심리의 정답이 아닙니다.** 입력이 없으면 조건 불충족으로 처리하지 말고 판정 보류해야 합니다. 미조작 판정에는 관측 구간과 기록의 완전성도 필요합니다.

## 두 자료의 연결에서 보류한 사항

PDF에는 시선, 손 왕복, 반복 오류음 횟수, 정답 버튼 판정이 없습니다. 따라서 R1~R8을 적용한 결과를 만들어 넣지 않았습니다. BTN_CUTTING_OXYGEN_OFF를 STOP이나 EMERGENCY_STOP으로 임의 변환하지 않습니다.

HTML 원문은 time_s를 사용합니다. 통합 파일은 time_ms를 사용하며, 같은 실험에 연결하려면 `time_ms = time_s * 1000 + offset_ms`로 기준점을 맞춰야 합니다. HTML의 0·8·20초와 PDF의 10·12.4·12.43초는 별도 사례이므로 합치지 않습니다.

원문 JSON의 schema_version=2.0은 설계 문서 버전, input_schema의 1.0은 합성 입력 버전입니다. 통합 패키지는 별도로 0.1.0을 사용합니다.
