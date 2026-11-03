# 출처와 반영 내역

기준 자료는 사용자가 제공한 `[은재] 1팀 공간 그래프 (1).pdf`와 `graph_design.html` 두 파일입니다. 이전 PDF의 수정 메모나 별도 데이터셋 연구 내용은 반영하지 않았습니다.

| 출처 | 반영 |
|---|---|
| PDF | 공간 구조, 시나리오, JSON, 쿼리 표, 촬영 정보 |
| HTML | DecisionPoint, NEXT/UPDATE, Belief, 규칙 R1~R8, 합성 예시 |
| 이번 통합 | decision_graph 추가, 내부 JSON Pointer 연결, ms 통일, metadata, 결측 정책 문서화 |

PDF JSON은 examples/p4_cutting_error.source.json에 보존했습니다. PDF 줄바꿈으로 끊긴 문자열만 복구했습니다. HTML 내부 JSON은 config/decision-design.source.json에 보존했습니다.

통합 JSON은 metadata와 decision_graph만 추가했습니다. PDF의 기존 필드·값은 유지했습니다. PDF 표의 '판단 시각은 추가 필요' 문구는 실제 예시의 time_ms=12100에 맞춰 시나리오 문서에서 정리했습니다.

추가한 Decision 기록은 원본 자료의 실행 결과가 아니라, PDF 기록을 HTML 구조에 연결한 설계 예시입니다. 원문 HTML 합성 입력·예상 결과는 별도 파일로 보존합니다.
