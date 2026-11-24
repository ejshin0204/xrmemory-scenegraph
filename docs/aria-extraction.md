# Aria 녹화에서 씬그래프 추출

실제 Project Aria 녹화(`261104_test0`, 9분 25초, 정상 절차 rehearsal)에서 이 레포의 씬그래프를 만든 방법이다. 결과는 `examples/aria_261104_test0/scenegraph.json`, 시각화는 `viewer/index.html`이다.

## 입력과 결과

| 원본 | 처리 | 씬그래프 필드 | 출처 구분 |
|---|---|---|---|
| camera-rgb.mp4 (10 fps) | LCD 글자가 바뀌기 시작한 첫 프레임 판독 | `states` (SCREEN_1.display_text) 7구간 | 관측, 수작업 |
| camera-rgb.mp4 + handtracking.csv | 화면이 바뀌기 직전 손가락이 키에 닿은 프레임. 손바닥이 쉬는 위치에서 12 cm 넘게 움직인 구간을 접근 구간으로 기록 | `events` button_press 6회 | 관측, 수작업 + 자동 |
| vio_high_frequency.csv | 머리 앙각 > −28°가 0.5초 이상 | `events` look_at_machine 2회 | 관측, 자동 |
| mic.wav | 증폭 → Whisper 받아쓰기 → 교정 → 관찰·판단·의도·계획 분류 | `observations` 17, `interpretations` 24 | 구술, 수작업 |
| 의도 발언 + 버튼 누름 | "…버튼을 누르겠습니다" 끝 기준 10초 안의 누름에 버튼 연결 | `events[].target_id`, `interpretations[].selected_action_id` | 구술, 자동 |
| 상태 확인 발언 | "제어가 활성 상태로 바뀌었습니다" 등 | `states[].task_state`, `reported_phase` | 구술, 수작업 |
| 위 결과 전체 | 시간순 정렬, 작업 상태가 바뀌면 다음 DP | `decision_graph` UPDATE 56건 | 자동 |
| eyegaze.csv | DP 구간별 유효 샘플 비율 | `nodes[].observed_window.gaze_valid_ratio` | 자동 |

수작업 부분은 `examples/aria_261104_test0/annotation.json`에 있다. 원본 녹화(VRS와 추출 스트림)는 레포에 없다.

## 시간 기준

- `trial_start` = camera-rgb 0번 프레임의 `t_device_ns`. 모든 스트림이 같은 Aria 장치 시계를 쓴다.
- 오디오 시각 → trial 시각: `time_ms = audio_s × 1000 + audio_offset_ms` (이 녹화는 −37.6 ms, manifest.json `mic.t0_ns`에서 계산).
- 영상 판독 시각은 ±100 ms (10 fps).

## Decision graph 갱신 규칙

1. events, states, observations, interpretations를 시간순으로 놓고 항목마다 UPDATE 기록을 하나 만든다. `evidence_refs`는 JSON Pointer.
2. 작업 상태(S0~S4)가 바뀌는 순간 다음 DP로 넘어간다. 상태를 바꾼 기록은 그 단계를 끝낸 DP에 넣는다.
3. 화면 상태 기록 직전 1초 안에 버튼 누름이 있고, 그 버튼(구술 기준)이 해당 DP의 절차 버튼이면 R1(Normal Execution)으로 둔다.
4. 위험도 발언이 없어 `belief`와 `expert_severity`는 모두 UNKNOWN이다.

## 스키마 확장 (0.1.0 대비)

- `interpretations[]`: 판단 기록이 여러 개라 배열로 저장했다 (design.md "복수 기록 형식은 추후 결정"). `interpretation`은 null. `kind`는 judgment / intention / plan.
- `interpretations[]`의 `stated_button_id`, `selected_action_id`, `withheld_action_ids`, `planned_action_ids`, `trigger`, `monitor_cues`.
- `observations[]`의 `text`(교정본)와 `transcript`(ASR 원문).
- `states[].attribute = display_text`: 실제 LCD는 밸브 상태가 아니라 모드 글자만 보여 준다. `task_state`, `reported_phase`는 구술로 확인한 작업 상태.
- `events[]`의 `key_group`, `physical_key`, `target_status`, `target_evidence`, `approach`, 그리고 `look_at_machine`·`key_contact` 유형.
- 객체 `MACHINE_PROJECTION`, `PHYS_FKEY_ROW`, `PHYS_RIGHT_KEYPAD`, `BTN_IGNITE`.

## 가정 (확인 필요)

- A1: 상태 정의에 점화·천공 단계가 없어 점화 후는 S2, 천공 진행은 S3로 뒀다.
- A2: `BTN_IGNITE`는 레포 정의에 없는 버튼이라 추가했고 작업 제어 영역에 속한다고 가정했다.
- A3: 구술의 "화면"이 패널 LCD인지 영사 장비 화면인지 구분되지 않아 observations로만 기록했다.
- A4: R1의 "정상 버튼"은 구술한 의도 버튼이 DP 절차 버튼과 일치하는지로 판단했다 (점화는 DP3에 포함).

## 한계

- 실시간이 아닌 사후 추출이다. `selected_action_id`처럼 미래 사건을 가리키는 필드는 온라인 추론에 쓰면 안 된다 (scenario.md).
- 오류음·이상 사건이 없는 정상 시행이라 DP5에는 감시·대응 계획 발언만 있다.
- 우측 키패드에서 어느 키가 점화·예열·천공·자동절단인지, 제어판 실측 좌표, 작업자 숙련도는 없다.
- 받아쓰기 교정은 사람이 했다. 원 대본이 있으면 `annotation.json`의 `text`를 대조해야 한다.

## 재현

```bash
# 1. 받아쓰기 (tools/aria/transcribe_mic.py 상단의 ffmpeg 전처리 참고)
python3 tools/aria/transcribe_mic.py boost.wav examples/aria_261104_test0/transcript_mic.json large-v3-turbo

# 2. 씬그래프 생성
python3 -I tools/aria/build_scenegraph.py --data <aria_export_dir> \
  --annotation examples/aria_261104_test0/annotation.json \
  --transcript examples/aria_261104_test0/transcript_mic.json \
  --out examples/aria_261104_test0/scenegraph.json

# 3. 뷰어
python3 -m http.server   # 레포 루트에서
# http://localhost:8000/viewer/
```
