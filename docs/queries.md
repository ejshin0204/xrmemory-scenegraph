# Query → Output 예시

통합 JSON을 기준으로 작성한 질문·답변 예시.

| 질문 | 예상 답변 | 근거 |
|---|---|---|
| 절단산소 차단 버튼 ID는? | BTN_CUTTING_OXYGEN_OFF | objects |
| 어느 영역에 있어? | GAS_CONTROL_ZONE | part_of |
| 가스 제어 영역 버튼은? | 절단산소 차단, 예열가스 차단 | part_of |
| 누르면 기대되는 변화는? | SCREEN_1의 cutting_oxygen_opened=false | Affordance.effects |
| 오류음 당시 공급 표시는? | 10초에 true | events, states |
| 13초 공급 표시는? | 마지막 기록은 12.43초 false, 13초까지 유지 확인은 없음 | states |
| 무엇을 관찰했다고 했어? | 불꽃 흔들림과 절단 홈 불안정 지속 | observations |
| 관찰 구간은? | 10.5~12초 | observations |
| 판단 시각·위험도는? | 12.1초 HIGH 보고 | interpretation |
| 오류음 후 첫 기록된 버튼은? | 12.4초 절단산소 차단 | events |
| 누가 눌렀어? | 숙련자 HUMAN_1 | humans, events |
| 오류음부터 누름까지는? | 2.4초 | 12400-10000 ms |
| 누른 뒤 화면값은? | 30ms 후 true→false 기록 | events, states |
| 왜 차단했어? | 불안정 지속과 공급 표시를 근거로 선택했다고 보고 | interpretation.reason |
| 어느 판단 지점인가? | DP5 | decision_graph |
| 사용자가 HIGH라고 판단했나? | 12.1초 직접 보고가 있음 | interpretation, belief |
| 규칙상 Normal Execution인가? | 현재 정보로 판정하지 않음 | user_state=UNKNOWN |
| decision 최신 기록은? | decision_record_04, 12.43초 | DP5.latest_event_id |

30ms는 두 기록의 시간 차이며 인과관계 판정값은 아니다.
