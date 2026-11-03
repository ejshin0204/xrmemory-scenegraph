# 공간 구조와 기록 형식

## 기본 원칙

제어판은 MACHINE_1, 화면은 SCREEN_1, 작업자는 HUMAN_1, 버튼은 BTN_* ID를 사용한다. 작업자는 objects에 넣지 않는다. 밸브 상태는 SCREEN_1의 화면 표시값으로 기록한다.

| 필드 | 의미 |
|---|---|
| scene_id / trial_id / scenario | 배치, 실험, 시나리오 식별 |
| objects | 제어판 1개, 화면 1개, 영역 4개, 버튼 10개 |
| humans | 작업자 ID, Human 유형, 숙련도 |
| relations | id, source, type, target, layer |
| states | object_id, attribute, value, start_ms, end_ms, source |
| events | 사건 ID·종류·시각·출처; 조작 사건에는 actor_id, target_id |
| observations | 보고한 단서, 관측 구간, 작업자, 관련 사건, 출처 |
| interpretation | 판단 시각·위험도·이유·관찰 ID·선택 행동 ID |

## 레이어

- Semantic: 버튼 → 영역 → 제어판의 `part_of` 관계.
- Functional: 버튼 → 화면의 `controls` 관계. 어떤 속성을 바꾸는지는 effects로 명시한다.
- Affordance: `press`와 기대 효과. 현재 절단산소 차단 버튼만 effects가 명시돼 있다.
- Geometry: frame_id와 translation/rotation/scale, bounds. 예시 좌표 [120,80,0]의 단위·원점·축은 미정이다. null인 rotation·scale·bounds는 측정되지 않은 값이며 기본값으로 해석하지 않는다.

`SCREEN_1.cutting_oxygen_opened`는 설명용 표기이다. 실제로는 states의 object_id와 attribute 두 필드로 표현된다.

## 시간과 결측

통합 파일은 trial 시작을 0으로 하는 ms를 사용한다. 유한 구간은 [start_ms, end_ms)이다. end_ms=null은 종료가 기록되지 않았다는 뜻이며 이후 모든 시점까지 확인됐다는 뜻이 아닙니다.

관찰 보고와 영상 자체의 관측 사실은 다릅니다. participant_report는 작업자의 보고이다. 사후 인터뷰 녹음 시각을 당시 판단 시각으로 쓰지 않는다.

interpretation은 현재 단일 판단 기록이다. 복수 기록 형식은 추후 결정한다.
