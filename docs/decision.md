# Decision Graph

`decision_graph`는 한 실험에서 한 작업자의 판단 지점과 갱신 기록을 저장한다. 노드는 DecisionPoint, 에지는 NEXT와 UPDATE로 구성한다.

## 판단 지점

| ID | 의미 | 요구 상태 | 목표 상태 |
|---|---|---|---|
| DP1 | 시스템 활성화 | S0 | S1 |
| DP2 | 조건 로드 | S1 | S2 |
| DP3 | 예열 개시 | S2 | S3 |
| DP4 | 절단 개시 | S3 | S4 |
| DP5 | 절단 중 이상 감지 및 대응 판단 | S4 | S4 |

S0 시스템 비활성, S1 시스템 활성, S2 조건 로드 완료, S3 예열, S4 절단이다. DP4는 천공·자동절단 버튼을 한 판단 단계로 묶은 것으로 버튼 하나와 일대일 대응하지 않는다.

## 에지와 기록

- NEXT는 절차 순서를 나타내며 실제 수행 완료를 뜻하지 않는다.
- UPDATE는 이전 기록의 DP에서 현재 기록의 DP로 연결한다. 동일 source/target이면 records에 누적하며 같은 DP 내부 갱신은 self-loop이다.
- 첫 기록은 해당 DP의 self-loop에 저장한다.
- `previous_event_id`는 **이전 UPDATE 기록 ID**이다. 공간 사건 ID와는 별개다.
- `latest_event_id`는 해당 DP의 최신 UPDATE 기록 ID이다. 기록이 없으면 null이고 상태와 Belief는 UNKNOWN이다.

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

`interpretation.severity`는 작업자의 직접 보고이다. 숙련자의 보고라도 독립적으로 정한 `expert_severity`와 자동으로 같게 두지 않는다.

Belief의 source는 SELF_REPORT, BEHAVIORAL_HYPOTHESES, WEAK_BEHAVIORAL_EVIDENCE, INSUFFICIENT_EVIDENCE 중 하나이다. UNKNOWN은 별도의 위험 등급이 아니라 판단을 알 수 없다는 표시이다. 가설 ID는 확률이나 순위가 아닙니다.

통합 예시에서는 12.1초 HIGH 보고를 SELF_REPORT로 연결한다. 이후 기록은 마지막 보고를 유지하지만, 새로 판단했다고 주장하지 않는다. expert_severity와 user_state는 UNKNOWN, status는 INSUFFICIENT_EVIDENCE로 둔다. 

## 상태 추정 규칙

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

동시에 일치하면 우선순위가 가장 높은 규칙이 대표가 되고 나머지도 보존한다. 합성 위험도 기준은 이상음 2회 이상·불꽃 악화·절단 결과 악화가 함께 있으면 HIGH, 이상 단서가 있으나 결합 조건 미충족이면 MID, 이상음 0회·불꽃 정상·절단 결과 정상이면 LOW, 판단 근거 부족이면 UNKNOWN이다.

규칙과 임계값은 합성 예시용이며 검증 전이다. 입력이 부족하면 판정을 보류한다. 미조작 여부는 해당 구간의 기록이 확보된 경우에만 판단한다.

## 연결 기준

차단 예시에는 시선·손 왕복·반복 오류음·정답 버튼 정보가 없어 R1~R8의 판정을 보류했다. BTN_CUTTING_OXYGEN_OFF와 STOP·EMERGENCY_STOP의 대응도 미정이다.

HTML 원문은 time_s를 사용한다. 통합 파일은 time_ms를 사용하며, 같은 실험에 연결하려면 `time_ms = time_s * 1000 + offset_ms`로 기준점을 맞춰야 합니다. HTML의 0·8·20초와 PDF의 10·12.4·12.43초는 별도 사례이므로 합치지 않는다.

원문 JSON의 schema_version=2.0은 설계 문서 버전, input_schema의 1.0은 합성 입력 버전이다. 통합 패키지는 별도로 0.1.0을 사용한다.
