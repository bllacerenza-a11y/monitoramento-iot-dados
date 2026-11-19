"""Analyze simulated ESP32/DHT22 readings published to ThingSpeak."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
STATE = {0: "Normal", 1: "Atenção", 2: "Crítico", 3: "Falha"}
COLORS = {"Normal": "#2a9d8f", "Atenção": "#e9a23b", "Crítico": "#d64550", "Falha": "#596579"}


def load_readings(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path)
    required = {"created_at", "entry_id", "field1", "field2", "field3"}
    if required.difference(data.columns):
        raise ValueError(f"Colunas ausentes: {', '.join(sorted(required.difference(data.columns)))}")
    data = data.rename(columns={"field1": "temperature_c", "field2": "humidity_pct", "field3": "state_code"})
    data["created_at"] = pd.to_datetime(data["created_at"], errors="coerce", utc=True)
    for column in ("entry_id", "temperature_c", "humidity_pct", "state_code"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.sort_values("created_at", kind="stable").reset_index(drop=True)


def analyze(data: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    data = data.copy()
    data["state"] = data["state_code"].map(STATE).fillna("Desconhecido")
    data["gap_seconds"] = data["created_at"].diff().dt.total_seconds()
    data["session"] = data["gap_seconds"].gt(300).fillna(False).cumsum() + 1
    expected_missing = data["state_code"].eq(3) & data["temperature_c"].isna() & data["humidity_pct"].isna()
    invalid = (
        data["created_at"].isna() | data["entry_id"].isna()
        | ~data["state_code"].isin(STATE)
        | (data["state_code"].ne(3) & (data["temperature_c"].isna() | data["humidity_pct"].isna()))
        | data["temperature_c"].lt(-40) | data["temperature_c"].gt(80)
        | data["humidity_pct"].lt(0) | data["humidity_pct"].gt(100)
    )
    within_session = data["gap_seconds"].le(300)
    long_gap = within_session & data["gap_seconds"].gt(45)
    rapid_temp_change = (within_session & data["gap_seconds"].le(90)
                         & data["temperature_c"].diff().abs().gt(5)
                         & data["state_code"].ne(3))
    metrics = {
        "source": "Canal público ThingSpeak 3572190; ESP32/DHT22 simulado no Wokwi",
        "rows": int(len(data)),
        "first_utc": data["created_at"].min().isoformat() if len(data) else None,
        "last_utc": data["created_at"].max().isoformat() if len(data) else None,
        "sessions_gap_over_5min": int(data["session"].nunique()),
        "normal": int(data["state_code"].eq(0).sum()),
        "attention": int(data["state_code"].eq(1).sum()),
        "critical": int(data["state_code"].eq(2).sum()),
        "fault": int(data["state_code"].eq(3).sum()),
        "fault_with_expected_missing_values": int(expected_missing.sum()),
        "invalid_rows": int(invalid.sum()),
        "duplicate_entry_ids": int(data["entry_id"].duplicated().sum()),
        "within_session_gaps_over_45s": int(long_gap.sum()),
        "rapid_temperature_changes_over_5c": int(rapid_temp_change.sum()),
    }
    return data, metrics


def render(data: pd.DataFrame, metrics: dict, target: Path) -> None:
    fig = plt.figure(figsize=(15, 9), facecolor="#f3f7fb")
    grid = fig.add_gridspec(3, 2, height_ratios=[0.9, 2.4, 1.8], hspace=0.48, wspace=0.28)
    fig.text(0.055, 0.954, "MONITORAMENTO IoT", fontsize=22, weight="bold", color="#102a43")
    fig.text(0.055, 0.922, "ESP32 + DHT22 simulado · canal público ThingSpeak · horários em UTC",
             fontsize=10, color="#526b80")
    kpis = [("Leituras", metrics["rows"]), ("Sessões", metrics["sessions_gap_over_5min"]),
            ("Alertas", metrics["attention"] + metrics["critical"]), ("Falhas sinalizadas", metrics["fault"])]
    axk = fig.add_subplot(grid[0, :]); axk.axis("off")
    for i, (name, value) in enumerate(kpis):
        x = 0.02 + i * 0.25
        axk.text(x, 0.76, name, transform=axk.transAxes, color="#526b80", fontsize=10)
        axk.text(x, 0.23, str(value), transform=axk.transAxes, color="#102a43", fontsize=20, weight="bold")
    temp = fig.add_subplot(grid[1, 0]); humidity = fig.add_subplot(grid[1, 1])
    counts = fig.add_subplot(grid[2, 0]); quality = fig.add_subplot(grid[2, 1])
    for ax in (temp, humidity, counts):
        ax.set_facecolor("white")
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.grid(axis="y", color="#e5edf4", zorder=0)
    for _, group in data.groupby("session"):
        valid = group[group["state_code"].ne(3)]
        temp.plot(valid["created_at"], valid["temperature_c"], color="#087e8b", lw=1.5, alpha=0.75)
        humidity.plot(valid["created_at"], valid["humidity_pct"], color="#3d85c6", lw=1.5, alpha=0.75)
    for code, label in STATE.items():
        subset = data[data["state_code"].eq(code)]
        if code != 3:
            temp.scatter(subset["created_at"], subset["temperature_c"], s=18, color=COLORS[label], zorder=3)
    temp.set_title("Temperatura por sessão", loc="left", weight="bold", color="#102a43")
    temp.set_ylabel("°C")
    humidity.set_title("Umidade por sessão", loc="left", weight="bold", color="#102a43")
    humidity.set_ylabel("%")
    for ax in (temp, humidity):
        ax.tick_params(axis="x", rotation=25, labelsize=8)
    labels = list(STATE.values())
    counts.bar(labels, [metrics[x] for x in ("normal", "attention", "critical", "fault")],
               color=[COLORS[x] for x in labels], zorder=2)
    counts.set_title("Estados publicados", loc="left", weight="bold", color="#102a43")
    quality.axis("off")
    notes = ["QUALIDADE & LIMITES",
             f"• Falhas com valores ausentes esperados: {metrics['fault_with_expected_missing_values']}",
             f"• Registros inválidos: {metrics['invalid_rows']}",
             f"• IDs duplicados: {metrics['duplicate_entry_ids']}",
             f"• Intervalos > 45 s dentro de sessão: {metrics['within_session_gaps_over_45s']}",
             f"• Mudanças de temperatura > 5 °C: {metrics['rapid_temperature_changes_over_5c']}",
             "", "Pausas entre sessões não provam falha de rede.",
             "Mudanças bruscas refletem testes da simulação."]
    for j, line in enumerate(notes):
        quality.text(0.01, 0.94 - j * 0.105, line, transform=quality.transAxes,
                     fontsize=12 if j == 0 else 9.5, weight="bold" if j == 0 else "normal", color="#102a43")
    fig.text(0.055, 0.025, "Fonte: simulação acadêmica Wokwi → canal público ThingSpeak 3572190; snapshot incluído no repositório.",
             fontsize=9, color="#526b80")
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "thingspeak_snapshot.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "report")
    args = parser.parse_args()
    data, metrics = analyze(load_readings(args.input))
    args.out.mkdir(exist_ok=True, parents=True)
    data.to_csv(args.out / "processed_readings.csv", index=False)
    (args.out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    render(data, metrics, args.out / "dashboard.png")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
