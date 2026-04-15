"""
sigma/loader.py — Bulk load and hot-reload Sigma rules from a directory.

SigmaLoader:
  - Loads all *.yml files from a rules directory at startup
  - Compiles each rule into a CompiledRule
  - Watches the directory for changes (add/modify/delete) via watchdog
  - Thread-safe rule set access via a read-write lock pattern
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from cusplunk.sigma.compiler import CompiledRule, SigmaCompiler
from cusplunk.sigma.parser import SigmaParser, SigmaParseError

logger = logging.getLogger(__name__)


class SigmaLoader:
    """
    Thread-safe Sigma rule loader with hot-reload.

    Usage:
        loader = SigmaLoader("/etc/cusplunk/sigma/")
        loader.start()                          # begins watching for changes
        rules = loader.get_compiled_rules()     # returns current rule set
        loader.stop()                           # stop file watcher
    """

    def __init__(self, rules_dir: str | Path) -> None:
        self._rules_dir = Path(rules_dir)
        self._parser = SigmaParser()
        self._compiler = SigmaCompiler()
        self._lock = threading.RLock()
        self._compiled: dict[str, CompiledRule] = {}   # rule_id → CompiledRule
        self._path_to_id: dict[str, str] = {}          # file path → rule_id
        self._observer: object | None = None            # watchdog observer

    # ── Public API ────────────────────────────────────────────────

    def load(self) -> int:
        """
        Load all *.yml files from the rules directory.
        Returns count of successfully loaded rules.
        """
        if not self._rules_dir.exists():
            logger.warning("SigmaLoader: rules directory %s does not exist", self._rules_dir)
            return 0

        loaded = 0
        errors = 0
        for yml_path in sorted(self._rules_dir.rglob("*.yml")):
            if self._load_file(yml_path):
                loaded += 1
            else:
                errors += 1

        logger.info(
            "SigmaLoader: loaded %d rules from %s (%d errors)",
            loaded, self._rules_dir, errors,
        )
        return loaded

    def start(self) -> None:
        """Load rules and start the file watcher."""
        self.load()
        self._start_watcher()

    def stop(self) -> None:
        """Stop the file watcher."""
        if self._observer is not None:
            try:
                self._observer.stop()  # type: ignore[attr-defined]
                self._observer.join()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._observer = None

    def get_compiled_rules(self) -> list[CompiledRule]:
        """Return a snapshot of all currently loaded compiled rules."""
        with self._lock:
            return list(self._compiled.values())

    def rule_count(self) -> int:
        with self._lock:
            return len(self._compiled)

    def get_rule(self, rule_id: str) -> CompiledRule | None:
        with self._lock:
            return self._compiled.get(rule_id)

    # ── Internal ──────────────────────────────────────────────────

    def _load_file(self, path: Path) -> bool:
        try:
            rule = self._parser.parse_file(path)
            compiled = self._compiler.compile(rule)
            with self._lock:
                # Remove old entry if this file previously had a different rule_id
                old_id = self._path_to_id.get(str(path))
                if old_id and old_id != compiled.rule_id:
                    self._compiled.pop(old_id, None)
                self._compiled[compiled.rule_id] = compiled
                self._path_to_id[str(path)] = compiled.rule_id
            return True
        except SigmaParseError as e:
            logger.warning("SigmaLoader: parse error in %s: %s", path, e)
            return False
        except Exception as e:
            logger.warning("SigmaLoader: failed to compile %s: %s", path, e)
            return False

    def _remove_file(self, path: Path) -> None:
        str_path = str(path)
        with self._lock:
            rule_id = self._path_to_id.pop(str_path, None)
            if rule_id:
                self._compiled.pop(rule_id, None)
                logger.info("SigmaLoader: removed rule from %s (id=%s)", path, rule_id)

    def _start_watcher(self) -> None:
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler, FileSystemEvent  # type: ignore
        except ImportError:
            logger.warning(
                "SigmaLoader: watchdog not installed — hot-reload disabled. "
                "Install with: pip install watchdog"
            )
            return

        loader_ref = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event: FileSystemEvent) -> None:
                if not event.is_directory and event.src_path.endswith(".yml"):
                    logger.info("SigmaLoader: detected new rule file: %s", event.src_path)
                    loader_ref._load_file(Path(event.src_path))

            def on_modified(self, event: FileSystemEvent) -> None:
                if not event.is_directory and event.src_path.endswith(".yml"):
                    logger.info("SigmaLoader: detected modified rule file: %s", event.src_path)
                    loader_ref._load_file(Path(event.src_path))

            def on_deleted(self, event: FileSystemEvent) -> None:
                if not event.is_directory and event.src_path.endswith(".yml"):
                    logger.info("SigmaLoader: detected deleted rule file: %s", event.src_path)
                    loader_ref._remove_file(Path(event.src_path))

            def on_moved(self, event: FileSystemEvent) -> None:
                if not event.is_directory:
                    if hasattr(event, "src_path") and event.src_path.endswith(".yml"):
                        loader_ref._remove_file(Path(event.src_path))
                    if hasattr(event, "dest_path") and event.dest_path.endswith(".yml"):
                        loader_ref._load_file(Path(event.dest_path))

        observer = Observer()
        observer.schedule(_Handler(), str(self._rules_dir), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        logger.info("SigmaLoader: watching %s for rule changes", self._rules_dir)
