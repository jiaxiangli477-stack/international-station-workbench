"""Isolated, local-only release diagnostics for current reviewed product assets."""
from __future__ import annotations

from contextlib import redirect_stdout
import csv
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import uuid

import task_store as store


WORKBENCH_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WORKBENCH_ROOT.parent
SKILL_ROOT = PROJECT_ROOT / "vendor/product-intelligence-v2-2.4.0/reviewed/product-intelligence-v2"
SOURCE_MANIFEST = SKILL_ROOT.parent / "skill-source.json"
QUALITY_ROOT = WORKBENCH_ROOT / ".state/product-quality/runs"
EXPECTED_SKILL = "alibaba-product-intelligence-v2"
EXPECTED_VERSION = "2.4.0"
APPROVED_MANIFEST_SHA256 = "785e09a2fba7168224db404ec2bcc5005a11f4868e11df0f3dc8c400e08c7bbe"
SOURCE_FILE_PREFIXES = ("config/", "contracts/", "product_intelligence/")
SOURCE_ROOT_FILES = {"SKILL.md", "README.md", "pyproject.toml"}
REQUIRED_RUNTIME_FILES = {
    "SKILL.md", "pyproject.toml", "config/scoring_rules.json",
    "config/scoring_fields.schema.json",
    "product_intelligence/__init__.py", "product_intelligence/__main__.py",
    "product_intelligence/cli.py", "product_intelligence/vision.py",
    "product_intelligence/scorer.py", "product_intelligence/release_dashboard.py",
    "product_intelligence/asset_audit.py", "product_intelligence/importer.py",
}
PRODUCT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
SPEC_KEYS = {"spec", "specification", "product_specification", "product_spec", "net_weight", "net_content"}
FIELD_ALIASES = {
    "product_name": "title", "title": "title",
    "main_ingredient": "main_ingredient", "core_ingredient": "main_ingredient",
    "ingredient": "main_ingredient", "dosage_form": "dosage_form", "form": "dosage_form",
    "product_specification": "specification", "specification": "specification",
    "product_spec": "specification", "spec": "specification", "net_weight": "specification",
    "net_content": "specification", "price": "price", "moq": "moq",
    "certification": "certifications", "certifications": "certifications",
    "has_oem": "has_oem", "has_odm": "has_odm", "has_private_label": "has_private_label",
    "has_supply_ability": "has_supply_ability", "has_b2b_evidence": "has_b2b_evidence",
}
PIPELINE = [
    "doctor", "import-products", "audit-assets", "analyze-images:manifest_only",
    "import-visual-analysis", "score", "release-dashboard",
]


def runtime_source_files(manifest: dict) -> list[str]:
    """Choose executable source/config files; never open old cache, reports, or data."""
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("Skill source manifest 缺少文件哈希表")
    selected = []
    for raw in files:
        relative = str(raw).replace("\\", "/")
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "__pycache__" in path.parts:
            continue
        if relative in SOURCE_ROOT_FILES or (relative.startswith(SOURCE_FILE_PREFIXES)
                and path.suffix in {".py", ".json"}):
            if relative.startswith("product_intelligence/") and path.suffix != ".py":
                continue
            selected.append(relative)
    selected = sorted(set(selected))
    missing = REQUIRED_RUNTIME_FILES - set(selected)
    if missing:
        raise ValueError("Skill runtime source manifest 缺少必要文件：" + ", ".join(sorted(missing)))
    return selected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def skill_preflight(skill_root: Path | None = None, manifest_path: Path | None = None) -> dict:
    root_input = Path(skill_root or SKILL_ROOT)
    manifest_input = Path(manifest_path or SOURCE_MANIFEST)
    if root_input.is_symlink() or manifest_input.is_symlink():
        raise ValueError("Product Intelligence reviewed source 不接受符号链接")
    root, manifest_file = root_input.resolve(), manifest_input.resolve()
    if not root.is_dir() or not manifest_file.is_file():
        raise ValueError("Product Intelligence reviewed source 副本或来源清单不可用")
    if (root / "config/calibration_overlay.json").exists():
        raise ValueError("检测到外部评分校准覆盖；隔离诊断拒绝读取")
    if _sha256(manifest_file) != APPROVED_MANIFEST_SHA256:
        raise ValueError("Product Intelligence source manifest 哈希不匹配")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("Product Intelligence source manifest 无法读取") from error
    if manifest.get("skill") != EXPECTED_SKILL or manifest.get("version") != EXPECTED_VERSION:
        raise ValueError("Product Intelligence Skill 名称或版本不匹配")
    files = runtime_source_files(manifest)
    actual = {}
    for relative in files:
        path = root / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Product Intelligence runtime source 文件缺失或路径无效：" + relative)
        digest = _sha256(path)
        expected = manifest["files"].get(relative) or manifest["files"].get(relative.replace("/", "\\"))
        if digest != expected:
            raise ValueError("Product Intelligence runtime source 哈希不匹配：" + relative)
        actual[relative] = digest
    try:
        import tomllib
        package = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Product Intelligence pyproject.toml 无效") from error
    if package.get("project", {}).get("version") != EXPECTED_VERSION:
        raise ValueError("Product Intelligence pyproject 版本不匹配")
    fingerprint = hashlib.sha256(json.dumps(actual, sort_keys=True).encode("utf-8")).hexdigest()
    return {"available": True, "version": EXPECTED_VERSION, "verified_files": len(actual),
            "source_fingerprint": fingerprint, "manifest_sha256": APPROVED_MANIFEST_SHA256}


def _confirmed_fields(product: dict) -> tuple[dict, dict]:
    plan = product.get("attributePlan") or {}
    manifest = plan.get("manifest") or {}
    sources = plan.get("field_sources") or {}
    confirmed, evidence = {}, {}
    for path, source in sources.items():
        if (not isinstance(source, dict) or source.get("kind") != "CONFIRMED"
                or not str(source.get("source") or "").strip()
                or not isinstance(path, str)):
            continue
        parts = path.split(".")
        value = manifest
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                value = None
                break
        if value in (None, "", [], {}) or (isinstance(value, str) and value.strip().upper() == "TO_CONFIRM"):
            continue
        key = ".".join(parts[1:]) if parts[0] == "fields" else path
        confirmed[key] = value
        evidence[key] = {"status": "CONFIRMED", "source": str(source["source"])[:300]}
    return confirmed, evidence


def _select_reviewed_images(product: dict) -> list[dict]:
    from single_approval_flow import require_hero, visual_gaps
    import attribute_plan

    revision = product["revision"]
    visual = product.get("visual") or {}
    if (visual.get("job") and visual.get("revision") == revision
            and product.get("approvedVisual") == visual.get("job")):
        if not attribute_plan.artifact_matches(product, visual):
            raise ValueError("已审核套图与当前属性方案不匹配")
        if visual_gaps(product):
            raise ValueError("已审核套图当前质检不完整，诊断已阻断")
        return [dict(row, sourceJob=visual["job"], sourceRevision=revision)
                for row in visual.get("images", [])]
    hero = product.get("hero") or {}
    approval = product.get("heroApproval") or {}
    if approval:
        require_hero(product)
        row = hero["images"][0]
        return [dict(row, sourceJob=hero["job"], sourceRevision=revision)]
    return []


def _copy_reviewed_images(product: dict, images: list[dict], product_dir: Path) -> list[dict]:
    from skill_jobs import artifact

    registered = []
    for row in images:
        slot = str(row.get("slot") or "")
        if not re.fullmatch(r"m[1-6]|d1|d2|d3|d4|df|d5|d6|dfac|d7|dc|drev", slot):
            raise ValueError("当前批准图片包含不在新版合同中的slot：" + slot)
        source_root = store.STATE / "runs" / str(row.get("sourceJob") or "")
        source = artifact(source_root, row.get("file") or "")
        section = "main" if slot.startswith("m") else "detail"
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("已审核图片格式不支持：" + slot)
        target = product_dir / section / (slot + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hash, copied_hash = _sha256(source), _sha256(target)
        if source_hash != copied_hash:
            raise ValueError("已审核图片复制哈希不一致：" + slot)
        registered.append({"slot": slot, "asset_type": section, "file": target.relative_to(product_dir).as_posix(),
                           "sha256": copied_hash, "sourceJob": row["sourceJob"],
                           "sourceRevision": row["sourceRevision"], "copied": True})
    if len({row["slot"] for row in registered}) != len(registered):
        raise ValueError("当前批准图片slot重复，诊断已阻断")
    return registered


def _load_cli(skill_root: Path):
    package_name = "_workbench_product_intelligence_240"
    package_init = skill_root / "product_intelligence" / "__init__.py"
    existing = sys.modules.get(package_name)
    if existing and Path(existing.__file__).resolve() != package_init.resolve():
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        existing = None
    if existing is None:
        spec = importlib.util.spec_from_file_location(
            package_name, package_init,
            submodule_search_locations=[str(package_init.parent)],
        )
        if spec is None or spec.loader is None:
            raise ValueError("Product Intelligence package import spec 不可用")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
    return importlib.import_module(package_name + ".cli")


def _run_cli(cli, args: list[str]) -> dict:
    if "openai_compatible" in args or "--base-url" in args or "--api-key-env" in args or "--model" in args:
        raise ValueError("quality adapter 禁止远程 provider 与 endpoint 参数")
    if args and args[0] == "analyze-images":
        if args.count("--provider") != 1 or args[args.index("--provider") + 1] != "manifest_only":
            raise ValueError("quality adapter 的图像provider必须固定为 manifest_only")
    output = io.StringIO()
    with redirect_stdout(output):
        status = cli.main(args)
    text = output.getvalue().strip()
    if status != 0:
        raise ValueError("Product Intelligence 阶段失败：" + (args[0] if args else "unknown"))
    try:
        payload = json.loads(text.splitlines()[-1]) if text else {}
    except (ValueError, IndexError):
        payload = {"output": text[:500]}
    return payload


def _phase_summary(stage: str, payload: dict) -> dict:
    fields = {
        "doctor": ("ok", "products", "config_count", "missing_tables"),
        "import-products": ("imported", "added", "updated", "unchanged", "errors"),
        "audit-assets": ("products", "risks"),
        "analyze-images:manifest_only": ("products", "analyzed", "failed"),
        "import-visual-analysis": ("imported", "skipped", "structural_records"),
        "score": ("scored", "asset_risk_products"),
        "release-dashboard": ("products",),
    }.get(stage, ())
    summary = {key: payload[key] for key in fields if key in payload}
    if stage == "release-dashboard":
        summary["generated"] = bool(payload.get("index"))
    if stage == "import-products":
        summary["warning_count"] = len(payload.get("warnings") or [])
    if stage == "import-visual-analysis":
        summary["warning_count"] = len(payload.get("warnings") or [])
    return summary


def _manifest_only_import(source_jsonl: Path, import_jsonl: Path) -> int:
    count = 0
    with source_jsonl.open("r", encoding="utf-8") as source, import_jsonl.open("w", encoding="utf-8") as output:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            analysis = row.get("analysis") or {}
            if analysis.get("provider") != "manifest_only" or analysis.get("source") != "manifest":
                raise ValueError("analyze-images returned a non-manifest provider")
            analysis["status"] = "missing"
            analysis["source"] = "manifest_only_structural_audit"
            analysis["error"] = "manifest_only_no_semantic_visual_evidence"
            analysis["risk_flags"] = list(dict.fromkeys([*(analysis.get("risk_flags") or []), "visual_analysis_missing"]))
            row["analysis"] = analysis
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _safe_product_id(value: str) -> str:
    if not isinstance(value, str) or not PRODUCT_ID_RE.fullmatch(value):
        raise ValueError("产品编号无效")
    return value


def _safe_run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise ValueError("诊断编号无效")
    return value


def diagnose(product_id: str, expected_revision: int) -> dict:
    product_id = _safe_product_id(product_id)
    if type(expected_revision) is not int:
        raise ValueError("必须提供当前产品版本")
    product = store.product(product_id)
    if product.get("revision") != expected_revision:
        raise ValueError("产品版本已变化，请刷新后重新诊断")
    source = skill_preflight()
    images = _select_reviewed_images(product)
    confirmed_fields, field_evidence = _confirmed_fields(product)

    run_id = uuid.uuid4().hex
    product_root = QUALITY_ROOT / product_id
    run_root = product_root / run_id
    inputs_root = run_root / "inputs"
    products_root = inputs_root / "products"
    product_dir = products_root / product_id
    run_root.mkdir(parents=True, exist_ok=False)
    try:
        product_dir.mkdir(parents=True)
        image_registry = _copy_reviewed_images(product, images, product_dir)
        attrs = {key: value for key, value in confirmed_fields.items()
                 if "." not in key and key in (product.get("attributePlan") or {}).get("manifest", {}).get("fields", {})}
        if "product_name" in confirmed_fields:
            attrs["title"] = confirmed_fields["product_name"]
        elif "title" in confirmed_fields:
            attrs["title"] = confirmed_fields["title"]
        (product_dir / "attributes.json").write_text(json.dumps(attrs, ensure_ascii=False, indent=2), encoding="utf-8")
        (inputs_root / "classification.csv").write_text("产品ID,分类\n" + product_id + ",\n", encoding="utf-8-sig")
        shutil.copyfile(SKILL_ROOT / "config/scoring_fields.schema.json", inputs_root / "scoring_fields.json")
        db_path = run_root / "diagnostic.sqlite3"
        raw_visual = run_root / "manifest-visual.jsonl"
        import_visual = run_root / "visual-import.jsonl"
        dashboard_root = run_root / "release-dashboard"
        cli = _load_cli(SKILL_ROOT)
        phase_receipts = []
        network_env = {key: "" for key in ("PI_VISION_API_KEY", "PI_VISION_MODEL", "PI_VISION_BASE_URL")}
        network_env.update({"PRODUCT_INTELLIGENCE_FEATURE_CACHE": str(run_root / "feature-cache.json"),
                            "PYTHONDONTWRITEBYTECODE": "1"})
        previous_env = {key: os.environ.get(key) for key in network_env}
        try:
            os.environ.update(network_env)
            stages = [
                ("doctor", ["doctor", "--db", str(db_path)]),
                ("import-products", ["import-products", "--db", str(db_path), "--products", str(products_root),
                                      "--scoring-fields", str(inputs_root / "scoring_fields.json"),
                                      "--classification", str(inputs_root / "classification.csv"), "--mode", "full"]),
                ("audit-assets", ["audit-assets", "--db", str(db_path), "--products", str(products_root)]),
                ("analyze-images:manifest_only", ["analyze-images", "--products", str(products_root), "--provider", "manifest_only", "--out", str(raw_visual)]),
            ]
            for stage, args in stages:
                output = _run_cli(cli, args)
                phase_receipts.append({"stage": stage, "status": "completed", "summary": _phase_summary(stage, output)})
            manifest_records = _manifest_only_import(raw_visual, import_visual)
            output = _run_cli(cli, ["import-visual-analysis", "--db", str(db_path), "--file", str(import_visual)])
            phase_receipts.append({"stage": "import-visual-analysis", "status": "completed",
                                   "summary": _phase_summary("import-visual-analysis", {**output, "structural_records": manifest_records})})
            output = _run_cli(cli, ["score", "--db", str(db_path)])
            phase_receipts.append({"stage": "score", "status": "completed", "summary": _phase_summary("score", output)})
            output = _run_cli(cli, ["release-dashboard", "--db", str(db_path), "--out", str(dashboard_root)])
            phase_receipts.append({"stage": "release-dashboard", "status": "completed", "summary": _phase_summary("release-dashboard", output)})
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        if not (dashboard_root / "index.html").is_file() or not (dashboard_root / "products" / f"{product_id}.html").is_file():
            raise ValueError("release-dashboard 未生成当前产品报告")
        cli_pkg = sys.modules[cli.__package__]
        db_module = importlib.import_module(cli.__package__ + ".database")
        from contextlib import closing
        with closing(db_module.connect(db_path)) as connection:
            score = connection.execute(
                "SELECT quality_score, market_score, prediction_score, confidence, risk_flags, evidence_json "
                "FROM pre_scores WHERE product_id=? ORDER BY created_at DESC, pre_score_id DESC LIMIT 1",
                (product_id,),
            ).fetchone()
            asset_rows = connection.execute(
                "SELECT asset_type, file_path, file_hash, width, height, risk_flags FROM assets WHERE product_id=? ORDER BY asset_type,file_path",
                (product_id,),
            ).fetchall()
        if score is None:
            raise ValueError("Skill score 阶段没有为当前产品写入评分记录")
        risk_flags = json.loads(score["risk_flags"] or "[]")
        evidence = json.loads(score["evidence_json"] or "{}")
        missing_evidence = []
        if "market_evidence_missing" in risk_flags:
            missing_evidence.append("market_evidence_missing")
        missing_evidence.append("visual_analysis_missing")
        has_spec = any(key.lower() in SPEC_KEYS for key in confirmed_fields)
        if not has_spec:
            missing_evidence.append("product_specification_missing")
        report = {
            "schema_version": 1, "status": "completed", "product_id": product_id,
            "revision": expected_revision, "run_id": run_id,
            "source_skill": {"name": EXPECTED_SKILL, "version": source["version"],
                             "source_fingerprint": source["source_fingerprint"]},
            "pipeline": PIPELINE,
            "phases": phase_receipts,
            "confirmed_fields": confirmed_fields,
            "field_evidence": field_evidence,
            "images": image_registry,
            "image_manifest_validation": "structural_only",
            "visual_evidence_status": "missing",
            "market_evidence_status": "missing",
            "performance_evidence_status": "missing",
            "missing_evidence": list(dict.fromkeys(missing_evidence)),
            "quality_score": score["quality_score"],
            "market_score": None if "market_evidence_missing" in risk_flags else score["market_score"],
            "prediction_score": None if missing_evidence else score["prediction_score"],
            "confidence": score["confidence"], "risk_flags": list(dict.fromkeys(risk_flags + missing_evidence)),
            "release_status": "HOLD" if missing_evidence else "REVIEW_REQUIRED",
            "release_dashboard_generated": True,
            "assets": [{"type": row["asset_type"], "file": Path(row["file_path"]).name,
                        "sha256": row["file_hash"], "width": row["width"], "height": row["height"],
                        "risk_flags": json.loads(row["risk_flags"] or "[]")} for row in asset_rows],
            "score_provenance": {"formula": evidence.get("formula", ""),
                                 "visual_score_source": evidence.get("visual_score_source", "missing")},
        }
        _write_json_atomic(run_root / "diagnostic.json", report)
        _write_json_atomic(product_root / "latest.json", {"run_id": run_id, "revision": expected_revision})
        return report
    except Exception as error:
        failed = {"schema_version": 1, "status": "failed", "product_id": product_id,
                  "revision": expected_revision, "run_id": run_id,
                  "error": type(error).__name__, "missing_evidence": ["diagnostic_failed"],
                  "risk_flags": ["diagnostic_failed"], "release_status": "HOLD",
                  "source_skill": {"name": EXPECTED_SKILL, "version": source["version"]}}
        _write_json_atomic(run_root / "diagnostic.json", failed)
        _write_json_atomic(product_root / "latest.json", {"run_id": run_id, "revision": expected_revision})
        raise


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_report(product_id: str, run_id: str) -> dict:
    product_id, run_id = _safe_product_id(product_id), _safe_run_id(run_id)
    root = QUALITY_ROOT.resolve()
    path = (root / product_id / run_id / "diagnostic.json").resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError("诊断报告不存在")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("product_id") != product_id or report.get("run_id") != run_id:
        raise ValueError("诊断报告身份不匹配")
    return report


def latest(product_id: str, current_revision: int | None = None) -> dict | None:
    product_id = _safe_product_id(product_id)
    pointer = QUALITY_ROOT / product_id / "latest.json"
    if not pointer.is_file() or pointer.is_symlink():
        return None
    data = json.loads(pointer.read_text(encoding="utf-8"))
    report = read_report(product_id, data.get("run_id", ""))
    revision = current_revision
    if revision is None:
        revision = store.product(product_id).get("revision")
    if report.get("revision") != revision:
        return None
    return report


def latest_diagnostics() -> list[dict]:
    summaries = []
    for product in store.records("products"):
        report = latest(product["id"], product.get("revision"))
        if report:
            summaries.append({key: report.get(key) for key in (
                "product_id", "revision", "run_id", "status", "quality_score", "missing_evidence",
                "release_status", "source_skill", "visual_evidence_status", "market_evidence_status",
            )})
    return summaries
