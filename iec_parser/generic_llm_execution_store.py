"""Minimal append-only results and deterministic restart checkpoints."""
from __future__ import annotations
import json,os
from pathlib import Path

class GenericLLMExecutionStore:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True);self.results_path=self.directory/"llm_interpretation_results.jsonl";self.audit_path=self.directory/"llm_execution_audit.jsonl";self.checkpoint_path=self.directory/"llm_execution_checkpoint.json"
    def completed_request_ids(self):
        if not self.checkpoint_path.is_file():return set()
        try:return set(json.loads(self.checkpoint_path.read_text(encoding="utf-8")).get("completed_request_ids") or [])
        except (OSError,json.JSONDecodeError):return set()
    def append_result(self,value):self._append(self.results_path,value)
    def append_audit(self,value):self._append(self.audit_path,value)
    def checkpoint(self,completed):
        data=json.dumps({"schema_version":"1.0","completed_request_ids":sorted(completed)},sort_keys=True,indent=2)+"\n";tmp=self.checkpoint_path.with_suffix(".tmp");tmp.write_text(data,encoding="utf-8");os.replace(tmp,self.checkpoint_path)
    @staticmethod
    def _append(path,value):
        with path.open("a",encoding="utf-8") as stream:stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n");stream.flush();os.fsync(stream.fileno())

__all__=["GenericLLMExecutionStore"]
