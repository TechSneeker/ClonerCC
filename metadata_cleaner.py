"""
metadata_cleaner.py
Processa vídeos MP4/MOV e injeta metadados idênticos aos de um iPhone 15 Pro,
simulando saída da câmera nativa iOS. Remove rastros de plataformas (TikTok,
Kwai, etc.) e salva como .MOV com container QuickTime.

Dependências externas:
  - ffmpeg  (deve estar no PATH)
  - exiftool (deve estar no PATH)

Instalar:
  ffmpeg   → https://ffmpeg.org/download.html
  exiftool → https://exiftool.org/
"""

import os
import random
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Metadados estáticos do iPhone 15 Pro ─────────────────────────────────────

STATIC_META = {
    "Make"                       : "Apple",
    "Model"                      : "iPhone 15 Pro",
    "Software"                   : "26.5",
    "com.apple.quicktime.make"   : "Apple",
    "com.apple.quicktime.model"  : "iPhone 15 Pro",
    "com.apple.quicktime.software": "26.5",
    # Esses campos no iPhone real ficam em [VideoKeys] (track-level via Core Media),
    # não no [Keys] global. Mantemos apenas os que o iPhone grava em [Keys].
}

# ─── Helpers para valores dinâmicos ───────────────────────────────────────────


def _random_creation_date() -> str:
    """
    Data/hora ISO 8601 nos últimos 30 dias, entre 8h e 20h,
    timezone -03:00 (Brasília).
    Formato: 2026-07-12T16:00:09-0300
    """
    tz_br = timezone(timedelta(hours=-3))
    now   = datetime.now(tz=tz_br)
    delta = random.randint(0, 30)
    day   = now - timedelta(days=delta)
    hour  = random.randint(8, 19)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    dt = day.replace(hour=hour, minute=minute, second=second, microsecond=0)
    # Formato sem ':' no offset pois exiftool/QuickTime esperam -0300 e não -03:00
    return dt.strftime("%Y-%m-%dT%H:%M:%S-0300")


def _random_lux() -> int:
    """Iluminância simulada de ambiente (10000–80000 milli-lux)."""
    return random.randint(10_000, 80_000)


def _random_orientation() -> int:
    """0=normal, 1=90°, 2=180°, 3=270°."""
    return random.choice([0, 0, 0, 1, 3])   # bias para retrato/paisagem normal


def _new_uuid() -> str:
    return str(uuid.uuid4()).upper()


def _build_dynamic_meta() -> dict:
    return {
        "com.apple.quicktime.creationdate"                   : _random_creation_date(),
        "com.apple.quicktime.scene-illuminance"              : str(_random_lux()),
        "com.apple.quicktime.milli-lux"                      : str(_random_lux()),
        "com.apple.quicktime.video-orientation"              : str(_random_orientation()),
        "com.apple.quicktime.full-frame-rate-playback-intent": "1",
        "com.apple.quicktime.uuid"                           : _new_uuid(),
        "com.apple.quicktime.segment-identifier"             : _new_uuid(),
    }


# ─── Verificação de dependências ──────────────────────────────────────────────


def _check_deps() -> tuple[bool, list[str]]:
    missing = []
    for cmd in ("ffmpeg", "exiftool"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    return len(missing) == 0, missing


# ─── Processo principal ───────────────────────────────────────────────────────


def clean_video(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """
    Recebe um arquivo MP4/MOV e produz um novo .MOV com metadados iPhone 15 Pro.

    Etapas:
      1. ffmpeg: copia streams sem re-encode, container QuickTime (mov),
                 remove todos os metadados existentes e injeta os estáticos.
      2. exiftool: injeta os campos Apple-specific (prefixo com.apple.*).

    Args:
        input_path : arquivo de entrada (.mp4 ou .mov)
        output_path: destino do arquivo final (padrão: mesmo nome com sufixo _iphone.MOV)

    Returns:
        Path do arquivo gerado.

    Raises:
        FileNotFoundError : se input_path não existir.
        RuntimeError      : se ffmpeg ou exiftool falharem.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {input_path}")

    ok, missing = _check_deps()
    if not ok:
        raise RuntimeError(
            f"Dependências ausentes: {', '.join(missing)}\n"
            "Instale ffmpeg (https://ffmpeg.org) e exiftool (https://exiftool.org) "
            "e adicione ao PATH."
        )

    if output_path is None:
        output_path = input_path.parent / (input_path.stem + "_iphone.MOV")
    output_path = Path(output_path)

    tmp_path = output_path.parent / (output_path.stem + "_tmp.MOV")

    # ── Etapa 1: ffmpeg ────────────────────────────────────────────────────────
    print(f"  [1/2] ffmpeg: copiando streams e removendo metadados antigos…")
    dynamic_meta = _build_dynamic_meta()

    # Todos os metadados (estáticos + dinâmicos) são injetados pelo ffmpeg
    # via -metadata. Isso garante que campos com hífen/ponto sejam gravados
    # corretamente no atom QuickTime Keys/udta sem depender do exiftool.
    all_meta = {**STATIC_META, **dynamic_meta}

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),

        # Remove todos os metadados do input
        "-map_metadata", "-1",

        # Copia streams sem re-encode
        "-c:v", "copy",
        "-c:a", "copy",

        # Container QuickTime
        "-f", "mov",
        "-movflags", "+faststart+use_metadata_tags",

        # Brand QuickTime — minor version 0x0000 = "0.0.0" como iPhone real
        "-brand", "qt  ",
        "-write_tmcd", "0",

        # Vendor ID Apple nos tracks (sobrescreve "FFmp" do ffmpeg)
        "-vendor", "appl",

        # Todos os metadados via -metadata
        *_ffmpeg_meta_args(all_meta),

        str(tmp_path),
    ]

    result = subprocess.run(
        ffmpeg_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falhou (código {result.returncode}):\n{result.stderr[-2000:]}"
        )

    # ── Etapa 2: exiftool — campos Keys que o ffmpeg não escreve corretamente ─
    print(f"  [2/2] exiftool: ajustando campos Keys Apple…")

    exiftool_cmd = [
        "exiftool",
        "-overwrite_original",
        "-api", "QuickTimeUTC=0",
        # Remove rastros de encoder (Lavf, etc.)
        "-Keys:Encoder=",
        "-QuickTime:Encoder=",
        "-Keys:CreationDate=" + dynamic_meta["com.apple.quicktime.creationdate"],
        "-Keys:Make=Apple",
        "-Keys:Model=iPhone 15 Pro",
        "-Keys:Software=26.5",
        "-Keys:FullFrameRatePlaybackIntent=1",
        # QuickTime movie-level dates (UTC) — preenche igual ao iPhone real
        "-QuickTime:CreateDate=" + _iso_to_exif_utc(dynamic_meta["com.apple.quicktime.creationdate"]),
        "-QuickTime:ModifyDate=" + _iso_to_exif_utc(dynamic_meta["com.apple.quicktime.creationdate"]),
        str(tmp_path),
    ]

    result = subprocess.run(
        exiftool_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # exiftool pode retornar código 1 com warnings não fatais — verifica
    # se realmente não fez nada antes de falhar
    if result.returncode != 0 and "Nothing to do" in result.stderr:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"exiftool falhou (código {result.returncode}):\n{result.stderr[-2000:]}"
        )

    # Renomeia tmp → destino final
    if output_path.exists():
        output_path.unlink()
    tmp_path.rename(output_path)

    print(f"  ✔ Arquivo gerado: {output_path}")
    return output_path


def _iso_to_exif_utc(iso_date: str) -> str:
    """
    Converte '2026-07-04T19:58:23-0300' para '2026:07:04 22:58:23'
    (UTC, formato exiftool QuickTime).
    """
    from datetime import datetime, timedelta
    # Parse manual pois strptime não aceita -0300 sem ':' em todas as plataformas
    dt_str  = iso_date[:19]           # '2026-07-04T19:58:23'
    tz_str  = iso_date[19:]           # '-0300'
    dt      = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
    sign    = 1 if tz_str[0] == '+' else -1
    hours   = int(tz_str[1:3])
    minutes = int(tz_str[3:5])
    offset  = timedelta(hours=hours, minutes=minutes) * sign
    dt_utc  = dt - offset
    return dt_utc.strftime("%Y:%m:%d %H:%M:%S")


def _ffmpeg_meta_args(meta: dict) -> list[str]:
    """Converte dict de metadados para flags -metadata key=value do ffmpeg."""
    args = []
    for k, v in meta.items():
        args += ["-metadata", f"{k}={v}"]
    return args


def _exiftool_meta_args(meta: dict) -> list[str]:
    """Converte dict para flags -TAG=VALUE do exiftool."""
    args = []
    for k, v in meta.items():
        # exiftool usa -TAG=value; campos com '.' precisam de aspas no valor
        args.append(f"-{k}={v}")
    return args


# ─── Processamento em lote ────────────────────────────────────────────────────


def _next_img_number(directory: Path, state_json_path: str | Path | None = None) -> int:
    """
    Retorna o próximo número disponível para nomear no padrão IMG_XXXX.
    Considera tanto os arquivos existentes na pasta quanto os já registrados
    no state.json do kwai-uploader, para nunca reutilizar um número já enviado.
    """
    import re
    pattern = re.compile(r"^IMG_(\d{4})\.", re.IGNORECASE)
    used = []

    # Arquivos em disco
    for f in directory.iterdir():
        m = pattern.match(f.name)
        if m:
            used.append(int(m.group(1)))

    # Entradas no state.json (inclui arquivos já apagados/publicados)
    if state_json_path:
        try:
            import json as _json
            sp = Path(state_json_path)
            if sp.exists():
                state = _json.loads(sp.read_text(encoding="utf-8"))
                for key in state:
                    m = pattern.match(Path(key).name)
                    if m:
                        used.append(int(m.group(1)))
        except Exception:
            pass

    return max(used, default=0) + 1


def clean_directory(
    directory: str | Path,
    pattern: str = "*.mp4",
    limit: int | None = None,
    overwrite: bool = False,
    log_fn=None,
    state_json_path: str | Path | None = None,
) -> list[Path]:
    """
    Processa todos os arquivos que casem com `pattern` em `directory`.

    Args:
        directory : pasta com os vídeos.
        pattern   : glob pattern (padrão "*.mp4").
        limit     : máximo de arquivos a processar (None = todos).
        overwrite : se True, sobrescreve arquivos *_iphone.MOV existentes.
        log_fn    : callable(str) para logging (padrão: print).

    Returns:
        Lista de Paths dos arquivos .MOV gerados.
    """
    log = log_fn or print
    directory = Path(directory)

    files = sorted(directory.glob(pattern))
    # Exclui arquivos já processados (para não reprocessar _iphone.MOV)
    files = [f for f in files if "_iphone" not in f.stem]

    if limit:
        files = files[:limit]

    if not files:
        log(f"Nenhum arquivo encontrado em: {directory} (pattern={pattern})")
        return []

    log(f"📁 {len(files)} arquivo(s) encontrado(s) para processar")

    generated = []
    next_num = _next_img_number(directory, state_json_path=state_json_path)

    for i, f in enumerate(files, 1):
        img_name = f"IMG_{next_num:04d}.MOV"
        out = directory / img_name

        # Garante que não sobrescreve um IMG existente
        while out.exists():
            next_num += 1
            img_name = f"IMG_{next_num:04d}.MOV"
            out = directory / img_name

        if not overwrite and out.exists():
            log(f"  [{i}/{len(files)}] ⏭ Já existe: {out.name}")
            generated.append(out)
            next_num += 1
            continue

        log(f"  [{i}/{len(files)}] 🎬 {f.name} → {img_name}")
        try:
            result = clean_video(f, out)
            generated.append(result)
            next_num += 1
            # Atualiza status no banco de dados para 'cleared'
            try:
                from db import get_db
                get_db().mark_cleared(str(f), str(result))
            except Exception:
                pass  # DB é opcional — não interrompe o processamento
            # Remove entrada do state.json do kwai-uploader para o novo arquivo
            # não ser ignorado por já ter sido processado com outro conteúdo
            if state_json_path:
                try:
                    import json as _json
                    _sp = Path(state_json_path)
                    if _sp.exists():
                        _state = _json.loads(_sp.read_text(encoding="utf-8"))
                        _key = str(result.resolve())
                        if _key in _state:
                            del _state[_key]
                            _sp.write_text(_json.dumps(_state, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            # Renomeia o sidecar .txt junto com o vídeo
            old_sidecar = f.with_suffix(".txt")
            new_sidecar = out.with_suffix(".txt")
            if old_sidecar.exists():
                old_sidecar.rename(new_sidecar)
                log(f"  [{i}/{len(files)}] 📝 Sidecar renomeado: {new_sidecar.name}")
            # Remove o .mp4 original após conversão bem-sucedida
            f.unlink(missing_ok=True)
            log(f"  [{i}/{len(files)}] 🗑 Original removido: {f.name}")
        except Exception as e:
            log(f"  [{i}/{len(files)}] ✖ Erro em {f.name}: {e}")

    log(f"\n✔ Processamento concluído — {len(generated)}/{len(files)} arquivo(s) gerado(s).")
    return generated


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Injeta metadados de iPhone 15 Pro em vídeos MP4/MOV."
    )
    parser.add_argument("input", help="Arquivo MP4/MOV ou pasta contendo vídeos")
    parser.add_argument("-o", "--output", default=None,
                        help="Arquivo ou pasta de saída (padrão: mesmo local com _iphone.MOV)")
    parser.add_argument("-n", "--limit", type=int, default=None,
                        help="Máximo de arquivos a processar (modo pasta)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Sobrescreve arquivos _iphone.MOV já existentes")
    args = parser.parse_args()

    ok, missing = _check_deps()
    if not ok:
        print(f"✖ Dependências ausentes: {', '.join(missing)}", file=sys.stderr)
        print("  Instale ffmpeg e exiftool e adicione ao PATH.", file=sys.stderr)
        sys.exit(1)

    p = Path(args.input)
    if p.is_dir():
        clean_directory(p, limit=args.limit, overwrite=args.overwrite)
    elif p.is_file():
        out = Path(args.output) if args.output else None
        clean_video(p, out)
    else:
        print(f"✖ Não encontrado: {p}", file=sys.stderr)
        sys.exit(1)
