"""Build an XRMemory scene graph (schema 0.1.0) from an Aria recording export.

Usage:
  python3 -I tools/aria/build_scenegraph.py \
      --data <aria_export_dir> \
      --annotation examples/aria_261104_test0/annotation.json \
      --transcript examples/aria_261104_test0/transcript_mic.json \
      --out examples/aria_261104_test0/scenegraph.json

<aria_export_dir> holds the per-stream files exported from the VRS
(camera-rgb_frames.csv, handtracking.csv, eyegaze.csv, vio_high_frequency.csv,
manifest.json, vrs_metadata.json). The raw recording is not in this repo.

annotation.json holds the manual parts: LCD transitions read from camera-rgb.mp4
(`video`) and the hand-corrected, classified think-aloud utterances (`speech`).
Everything else is computed here. See docs/aria-extraction.md.
"""
import argparse, csv, json, math, os, statistics

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--annotation", required=True)
ap.add_argument("--transcript", required=True)
ap.add_argument("--out", required=True)
ARGS = ap.parse_args()
DATA = ARGS.data

ANN = json.load(open(ARGS.annotation, encoding="utf-8"))
VIDEO = ANN["video"]
SPEECH = [(s["t0_s"], s["t1_s"], s["kind"], s.get("extra", {}), s["text"]) for s in ANN["speech"]]
EXCLUDED_SPEECH = ANN["excluded_speech"]
DP_BUTTONS = ANN["dp_buttons"]

# ---------------------------------------------------------------- helpers
def p(name):
    return os.path.join(DATA, name)

frames = [int(r["t_device_ns"]) for r in csv.DictReader(open(p("camera-rgb_frames.csv")))]
T0 = frames[0]
def fms(n):
    return round((frames[n] - T0) / 1e6)
def ns_to_ms(t):
    return (t - T0) / 1e6
END_MS = fms(len(frames) - 1)


def hand_reaches():
    rows = []
    for r in csv.DictReader(open(p("handtracking.csv"))):
        t = ns_to_ms(int(r["t_device_ns"]))
        def palm(side):
            c = r[side + "_confidence"]
            if c in ("", "nan") or float(c) < 0.5:
                return None
            return [float(r[f"{side}_palm_{a}"]) for a in "xyz"]
        rows.append((t, palm("left"), palm("right")))
    out = []
    for k, side in ((1, "left"), (2, "right")):
        pts = [x[k] for x in rows if x[k]]
        rest = [statistics.median(q[i] for q in pts) for i in range(3)]
        cur = None
        for row in rows:
            t, q = row[0], row[k]
            on = q is not None and math.dist(q, rest) > 0.12
            if on and cur is None:
                cur = [t, t]
            if on:
                cur[1] = t
            if not on and cur and t - cur[1] > 700:
                out.append((side, cur[0], cur[1])); cur = None
        if cur:
            out.append((side, cur[0], cur[1]))
    return [{"hand": s, "start_ms": round(a), "end_ms": round(b)} for s, a, b in out if b - a > 400]


def head_elevation():
    out, last = [], -1e9
    with open(p("vio_high_frequency.csv")) as f:
        r = csv.reader(f); h = next(r); ix = {k: i for i, k in enumerate(h)}
        for row in r:
            t = ns_to_ms(int(row[0]))
            if t < last + 100:
                continue
            last = t
            w, x, y, z = (float(row[ix["odometry_device_q" + c]]) for c in "wxyz")
            zz = 1 - 2 * (x * x + y * y)
            out.append((round(t), round(math.degrees(math.asin(max(-1, min(1, zz)))), 1)))
    return out


def look_up_episodes(elev, thr=-28.0, min_ms=500):
    eps, cur = [], None
    for t, e in elev:
        if e > thr:
            cur = cur or [t, t]; cur[1] = t
        elif cur:
            eps.append(cur); cur = None
    if cur:
        eps.append(cur)
    return [{"start_ms": a, "end_ms": b} for a, b in eps if b - a >= min_ms]


def gaze_series():
    return [(ns_to_ms(int(r["t_device_ns"])), r["combined_valid"] == "1") for r in csv.DictReader(open(p("eyegaze.csv")))]


def valid_ratio(gz, a, b):
    sel = [v for t, v in gz if a <= t < b]
    return round(sum(sel) / len(sel), 3) if sel else None


# ---------------------------------------------------------------- build
def main():
    reaches = hand_reaches()
    elev = head_elevation()
    looks = look_up_episodes(elev)
    gz = gaze_series()
    manifest = json.load(open(p("manifest.json")))
    vrsmeta = json.load(open(p("vrs_metadata.json")))
    transcript = json.load(open(ARGS.transcript, encoding="utf-8"))
    AUDIO_OFFSET_MS = (manifest["mic"]["t0_ns"] - T0) / 1e6  # audio t=0 relative to trial start
    a2t = lambda s: round(s * 1000 + AUDIO_OFFSET_MS)

    def reach_near(ms):
        hits = [r for r in reaches if r["start_ms"] - 1500 <= ms <= r["end_ms"] + 1500]
        if not hits:
            return None
        return {"start_ms": min(r["start_ms"] for r in hits), "end_ms": max(r["end_ms"] for r in hits),
                "hands": sorted({r["hand"] for r in hits}), "source": "handtracking.csv (palm displacement > 0.12 m)"}

    # ---- states (SCREEN_1 LCD text)
    states, prev, prev_start = [], VIDEO["initial"], 0
    for tr in VIDEO["transitions"]:
        ms = fms(tr["change_frame"])
        states.append((prev, prev_start, ms)); prev, prev_start = tr, ms
    states.append((prev, prev_start, None))
    states = [{"object_id": "SCREEN_1", "attribute": "display_text", "value": s["text"], "start_ms": a, "end_ms": b,
               "source": "video_annotation:camera-rgb", "task_state": s["task_state"], "reported_phase": s["phase"],
               "task_state_source": "participant_report:think_aloud"} for s, a, b in states]
    states[0]["start_note"] = "녹화 시작 시점의 표시값. 녹화 이전 상태는 알 수 없음."
    states[-1]["observed_until_ms"] = END_MS

    # ---- events
    ev = []
    ex = VIDEO["exploration"]
    ev.append({"type": "key_contact", "actor_id": "HUMAN_1", "target_id": None, "key_group": ex["key_group"],
               "time_ms": fms(ex["start_frame"]), "end_ms": fms(ex["end_frame"]), "observed_effect": "NONE",
               "approach": reach_near(fms(ex["start_frame"])),
               "description": "양손 검지로 F키 열을 짚거나 누름. 화면 변화 없음.", "source": "video_annotation:camera-rgb"})
    for lk in looks:
        ev.append({"type": "look_at_machine", "actor_id": "HUMAN_1", "target_id": "MACHINE_PROJECTION",
                   "time_ms": lk["start_ms"], "end_ms": lk["end_ms"],
                   "description": "머리를 들어 영사된 절단기를 봄 (머리 방향 기준, 시선 추적 아님).",
                   "source": "vio_high_frequency.csv (device z-axis elevation > -28°)"})
    for tr in VIDEO["transitions"]:
        ms = fms(tr["press_frame"])
        ev.append({"type": "button_press", "actor_id": "HUMAN_1", "target_id": None, "key_group": tr["key_group"],
                   "time_ms": ms, "time_precision_ms": 100, "observed_effect": f"SCREEN_1.display_text → {tr['text']}",
                   "approach": reach_near(ms), "source": "video_annotation:camera-rgb"})
    ev.sort(key=lambda e: e["time_ms"])
    ev = [{"id": f"event_{i:02d}", **e} for i, e in enumerate(ev, 1)]
    presses = [e for e in ev if e["type"] == "button_press"]

    # ---- speech -> observations / interpretations
    segs = transcript["segments"]
    def raw(t0, t1):
        return " ".join(s["text"] for s in segs if t0 - 0.01 <= s["start"] < t1 - 0.01)
    observations, interps = [], []
    for t0, t1, kind, extra, text in SPEECH:
        a, b = a2t(t0), a2t(t1)
        base = {"actor_id": "HUMAN_1", "start_ms": a, "end_ms": b, "text": text, "transcript": raw(t0, t1),
                "source": "participant_report:think_aloud(mic.wav)", "is_example": False}
        if kind == "observation":
            rel = next((e["id"] for e in ev if e["type"] == "look_at_machine" and e["time_ms"] < b and e["end_ms"] > a), None)
            if rel is None:
                prior = [e for e in presses if e["time_ms"] <= a]
                rel = prior[-1]["id"] if prior else None
            o = {"id": f"observation_{len(observations)+1:02d}", "related_event_id": rel, "cue": extra["cue"], **base}
            if "note" in extra:
                o["note"] = extra["note"]
            observations.append(o)
        else:
            it = {"id": f"interpretation_{len(interps)+1:02d}", "kind": kind, "time_ms": a, **base,
                  "severity": None, "severity_status": "NOT_REPORTED"}
            prev_end = interps[-1]["end_ms"] if interps else -1
            it["observation_ids"] = [o["id"] for o in observations if prev_end <= o["start_ms"] < a]
            if kind == "intention":
                nxt = next(e for e in presses if e["time_ms"] >= b - 500)
                assert nxt["time_ms"] - b < 10000, (t0, nxt)
                it["selected_action_id"] = nxt["id"]
                it["stated_button_id"] = extra["button"]
                nxt["target_id"] = extra["button"]
                nxt["target_status"] = "SELF_REPORTED_INTENT"
                nxt["target_evidence"] = it["id"]
                if extra.get("physical_key"):
                    nxt["physical_key"] = extra["physical_key"]
            for k in ("trigger", "planned_action_ids", "withheld_action_ids", "monitor_cues"):
                if k in extra:
                    it[k] = extra[k]
            interps.append(it)
    for o in observations:
        o.pop("is_example", None)
    # observations / interpretations: keep schema-ish key order
    observations = [{k: o[k] for k in ("id", "actor_id", "related_event_id", "cue", "text", "transcript", "start_ms", "end_ms", "source", "note") if k in o} for o in observations]

    # ---- decision graph
    s_change = [s for i, s in enumerate(states) if i > 0 and s["task_state"] != states[i - 1]["task_state"]]
    windows = [(0, "DP1")] + [(s["start_ms"], f"DP{int(s['task_state'][1]) + 1}") for s in s_change]
    def dp_at(ms):
        d = "DP1"
        for a, did in windows:
            if ms >= a:
                d = did
        return d
    def task_state_at(ms):
        cur = states[0]["task_state"]
        for s in states:
            if s["start_ms"] <= ms:
                cur = s["task_state"]
        return cur

    items = [("events", i, e["time_ms"]) for i, e in enumerate(ev)]
    items += [("states", i, s["start_ms"]) for i, s in enumerate(states) if i > 0]
    items += [("observations", i, o["start_ms"]) for i, o in enumerate(observations)]
    items += [("interpretations", i, it["start_ms"]) for i, it in enumerate(interps)]
    order = {"events": 0, "states": 1, "observations": 2, "interpretations": 3}
    items.sort(key=lambda x: (x[2], order[x[0]]))

    def inference(kind, i, dp):
        inf = {"expert_severity": "UNKNOWN", "user_state": "UNKNOWN", "status": "INSUFFICIENT_EVIDENCE",
               "primary_rule": None, "matched_rules": [],
               "belief": {"severity_candidates": ["UNKNOWN"], "source": "INSUFFICIENT_EVIDENCE", "hypotheses": []}}
        if kind == "states":
            s = states[i]
            press = next((e for e in presses if 0 <= s["start_ms"] - e["time_ms"] <= 1000), None)
            if press and press.get("target_id"):
                ok = press["target_id"] in DP_BUTTONS.get(dp, [])
                inf["rule_checks"] = {"R1": {"correct_button": ok, "button": press["target_id"], "button_source": press["target_evidence"],
                                             "transition_success": True, "transition_source": "LCD 변화 + 구술 상태 확인"}}
                if ok:
                    inf.update({"user_state": "Normal Execution", "status": "RULE_MATCHED", "primary_rule": "R1", "matched_rules": ["R1"]})
        return inf

    recs = []
    for kind, i, ms in items:
        if kind == "states" and states[i]["task_state"] != states[i - 1]["task_state"]:
            rec_dp = dp_at(ms - 1)  # completing transition belongs to the DP it completes
        else:
            rec_dp = dp_at(ms)
        recs.append((rec_dp, ms, kind, i))

    edges = [{"id": f"next_{k}", "type": "NEXT", "source": f"DP{k}", "target": f"DP{k+1}"} for k in range(1, 5)]
    upd, prev_id, prev_dp, latest = {}, None, None, {}
    for n, (dp, ms, kind, i) in enumerate(recs, 1):
        rid = f"decision_record_{n:02d}"
        key = (prev_dp or dp, dp)
        upd.setdefault(key, {"id": f"update_{key[0].lower()}_{dp.lower()}", "type": "UPDATE", "source": key[0], "target": dp, "records": []})
        upd[key]["records"].append({"id": rid, "time_ms": ms, "previous_event_id": prev_id, "task_state": task_state_at(ms),
                                    "observation": {"evidence_refs": [f"/{kind}/{i}"]}, "inference": inference(kind, i, dp)})
        prev_id, prev_dp, latest[dp] = rid, dp, rid
    edges += list(upd.values())

    starts = {did: a for a, did in windows}
    labels = [("DP1", "시스템 활성화", "S0", "S1"), ("DP2", "조건 로드", "S1", "S2"), ("DP3", "예열 개시", "S2", "S3"),
              ("DP4", "절단 개시", "S3", "S4"), ("DP5", "절단 중 이상 감지 및 대응 판단", "S4", "S4")]
    nodes = []
    for k, (did, lab, rq, tg) in enumerate(labels):
        a = starts[did]
        b = starts[labels[k + 1][0]] if k + 1 < len(labels) else END_MS
        nodes.append({"id": did, "label": lab, "required_state": rq, "target_state": tg, "type": "DecisionPoint",
                      "latest_event_id": latest.get(did),
                      "observed_window": {"start_ms": a, "end_ms": b, "gaze_valid_ratio": valid_ratio(gz, a, b),
                                          "look_at_machine_count": sum(a <= l["start_ms"] < b for l in looks),
                                          "button_press_count": sum(a <= e["time_ms"] < b for e in presses),
                                          "utterance_count": sum(a <= x["start_ms"] < b for x in observations + interps)}})
    nodes[4]["note"] = "오류음·이상 사건은 없었음. 감시 계획과 이상 시 대응 계획 발언만 기록됨."

    # ---- objects & relations
    objects = [
        {"id": "MACHINE_1", "type": "control_panel", "name": "제어판", "observed_label": "STARFIRE 키패드 + KAIST LCD"},
        {"id": "SCREEN_1", "type": "screen", "name": "표시 화면 (패널 LCD)"},
        {"id": "MACHINE_PROJECTION", "type": "projected_machine", "name": "영사된 절단기",
         "note": "전방 벽면에 영사된 가스 절단기 시뮬레이션. 불꽃·슬래그·커프 단서가 표시되는 곳."},
        {"id": "PHYS_FKEY_ROW", "type": "physical_key_group", "name": "F키 열 (ESC, F1~F7)"},
        {"id": "PHYS_RIGHT_KEYPAD", "type": "physical_key_group", "name": "우측 키패드 (숫자·색상 키)"},
        {"id": "SYSTEM_CONTROL_ZONE", "type": "region", "name": "시스템 제어 영역"},
        {"id": "OPERATION_CONTROL_ZONE", "type": "region", "name": "작업 제어 영역"},
        {"id": "GAS_CONTROL_ZONE", "type": "region", "name": "가스 제어 영역"},
        {"id": "ALARM_CONTROL_ZONE", "type": "region", "name": "알람 제어 영역"},
    ]
    buttons = [("BTN_SYSTEM_ACTIVATE", "시스템 활성화", "SYSTEM_CONTROL_ZONE"), ("BTN_LOAD_ALIGN", "조건 로드·정렬", "OPERATION_CONTROL_ZONE"),
               ("BTN_IGNITE", "점화", "OPERATION_CONTROL_ZONE"),
               ("BTN_PREHEAT_START", "예열 시작", "OPERATION_CONTROL_ZONE"), ("BTN_PIERCE_START", "천공 시작", "OPERATION_CONTROL_ZONE"),
               ("BTN_AUTO_RUN", "자동절단 시작", "OPERATION_CONTROL_ZONE"), ("BTN_CUTTING_OXYGEN_OFF", "절단산소 차단", "GAS_CONTROL_ZONE"),
               ("BTN_PREHEAT_GAS_OFF", "예열가스 차단", "GAS_CONTROL_ZONE"), ("BTN_STOP", "정지", "OPERATION_CONTROL_ZONE"),
               ("BTN_ACK", "알람 확인", "ALARM_CONTROL_ZONE"), ("BTN_RESET", "초기화", "SYSTEM_CONTROL_ZONE")]
    pressed = {e["target_id"]: e for e in presses if e.get("target_id")}
    for bid, name, _ in buttons:
        o = {"id": bid, "type": "button", "name": name, "Affordance": {"action": "press"}, "physical_key": None, "Geometry": None}
        if bid == "BTN_IGNITE":
            o["definition_status"] = "ADDED_FROM_THINK_ALOUD (레포 정의에 없음)"
        if bid in pressed:
            e = pressed[bid]
            o["physical_key"] = e.get("physical_key") or e["key_group"]
            o["Affordance"]["effects"] = [{"object_id": "SCREEN_1", "attribute": "display_text",
                                           "value": e["observed_effect"].split("→ ")[1], "status": "OBSERVED"}]
        objects.append(o)

    rel, n = [], 0
    def add(s, t, ty, layer, **kw):
        nonlocal n; n += 1
        rel.append({"id": f"relation_{n:02d}", "source": s, "type": ty, "target": t, "layer": layer, **kw})
    for z in ("SYSTEM_CONTROL_ZONE", "OPERATION_CONTROL_ZONE", "GAS_CONTROL_ZONE", "ALARM_CONTROL_ZONE", "SCREEN_1",
              "PHYS_FKEY_ROW", "PHYS_RIGHT_KEYPAD"):
        add(z, "MACHINE_1", "part_of", "Semantic")
    for bid, _, zone in buttons:
        add(bid, zone, "part_of", "Semantic", **({"status": "ASSUMED"} if bid == "BTN_IGNITE" else {}))
        add(bid, "SCREEN_1", "controls", "Functional")
    for g in ("PHYS_FKEY_ROW", "PHYS_RIGHT_KEYPAD"):
        add(g, "SCREEN_1", "controls", "Functional", status="OBSERVED")

    graph = {
        "scene_id": ANN["scene_id"],
        "trial_id": ANN["trial_id"],
        "scenario": ANN["scenario"],
        "objects": objects,
        "humans": [{"id": "HUMAN_1", "type": "Human", "role": None, "role_status": "UNKNOWN"}],
        "relations": rel,
        "states": states,
        "events": ev,
        "observations": observations,
        "interpretation": None,
        "interpretations": interps,
        "metadata": {
            "schema_version": "0.1.0",
            "is_example": False,
            "time_unit": "ms",
            "time_origin": "trial_start",
            "trial_start_definition": f"camera-rgb frame 0 (t_device_ns={T0})",
            "recording_end_ms": END_MS,
            "audio_offset_ms": round(AUDIO_OFFSET_MS, 1),
            "source": {"device": "Project Aria", "recording_profile": vrsmeta.get("recording_profile"),
                       "host_minus_device_ns": manifest["time"]["host_minus_device_ns"]},
            "coordinate_system": {"frame_id": "MACHINE_1", "unit": None, "origin": None, "axes": None, "status": "UNSPECIFIED"},
            "schema_extensions": [
                "interpretations: 판단 기록이 여러 개라 배열로 저장 (design.md: 복수 기록 형식은 추후 결정). interpretation은 null.",
                "interpretations[].kind: observation 외 발언을 judgment / intention / plan으로 구분",
                "states[].task_state, reported_phase: 구술로 확인한 작업 상태",
                "events[].target_status, target_evidence, key_group, physical_key",
            ],
            "assumptions": [
                {"id": "A1", "status": "HYPOTHESIS", "text": "레포 상태 정의(S0~S4)에 점화·천공 단계가 없어 점화 후는 S2, 천공 진행은 S3로 둠"},
                {"id": "A2", "status": "HYPOTHESIS", "text": "BTN_IGNITE는 레포에 없는 버튼이라 추가했고, 작업 제어 영역에 속한다고 가정"},
                {"id": "A3", "status": "HYPOTHESIS", "text": "구술의 '화면'이 패널 LCD인지 영사 장비 화면인지 구분되지 않아 observations(display_report)로만 기록"},
                {"id": "A4", "status": "HYPOTHESIS", "text": "R1의 '정상 버튼'은 구술한 의도 버튼이 해당 DP의 절차 버튼과 일치하는지로 판단 (점화는 DP3에 포함)"},
            ],
            "speech": {
                "asr": "faster-whisper large-v3-turbo, ko, VAD off; 입력 = mic.wav ch0~2 평균, 100–6000 Hz, +45 dB",
                "text_status": "text = 받아쓰기를 사람이 교정한 문장, transcript = ASR 원문",
                "excluded": EXCLUDED_SPEECH,
            },
            "not_available": ["error_sound(stimulus log)", "self-reported severity (위험도 발언 없음)",
                              "expert_severity", "panel 3D geometry", "operator expertise",
                              "physical key for BTN_IGNITE/PREHEAT/PIERCE/AUTO_RUN (우측 키패드 중 어느 키인지)"],
            "extraction": {
                "states": "camera-rgb.mp4 육안 판독, 10fps (±100ms). start_ms = LCD 재표시 시작 프레임. task_state는 구술 상태 확인",
                "button_press": "누름 직전 프레임(손가락 접촉) 육안 판독 + handtracking 접근 구간. target_id는 직전 의도 발언",
                "look_at_machine": "vio_high_frequency 머리 방향 앙각 > -28° 구간",
                "observations/interpretations": "mic.wav 받아쓰기 → 교정 → 관찰/판단/의도/계획 분류, 시각 = 오디오 시각 + audio_offset_ms",
            },
        },
        "decision_graph": {"actor_id": "HUMAN_1", "nodes": nodes, "edges": edges},
    }

    os.makedirs(os.path.dirname(os.path.abspath(ARGS.out)), exist_ok=True)
    with open(ARGS.out, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
        f.write("\n")
    kinds = {}
    for it in interps:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    print("events", len(ev), "states", len(states), "observations", len(observations), "interpretations", kinds, "records", len(recs))


if __name__ == "__main__":
    main()
