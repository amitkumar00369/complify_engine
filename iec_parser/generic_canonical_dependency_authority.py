"""Deterministic canonical dependency and invalidation authority (Step 48-I)."""
from __future__ import annotations
import copy,hashlib,json
from collections import Counter,defaultdict,deque
from pathlib import Path

SCHEMA_VERSION="CANONICAL_DEPENDENCY_MANIFEST_V1"
DEPENDENCY_POLICY="STEP48I_DEPENDENCY_POLICY_V1"
INVALIDATION_POLICY="STEP48I_INVALIDATION_POLICY_V1"
RECOMPUTE_POLICY="STEP48I_RECOMPUTE_POLICY_V1"
INTEGRITY_SCHEMA="CANONICAL_DEPENDENCY_INTEGRITY_V1"
STATES={"CURRENT","STALE","INVALID","NEEDS_RECOMPUTE"}
UNSTABLE={"timestamp","generated_at","generation_timestamp","started_at","completed_at","temp_path","output_directory","process_id","pid"}
PRODUCT_SPECIFIC_BRANCHES_ADDED=MODEL_SPECIFIC_BRANCHES_ADDED=REPORT_SPECIFIC_BRANCHES_ADDED=0
STANDARD_SPECIFIC_BRANCHES_ADDED=CLAUSE_SPECIFIC_BRANCHES_ADDED=GOLDEN_SPECIFIC_BRANCHES_ADDED=0

ARTIFACTS={
 "standard_kb":("standards/effective_kb.json","EFFECTIVE_KB"),"report_evidence":("report/report_evidence.json","REPORT_EVIDENCE"),"facts":("report/canonical_product_fact_ledger.json","CANONICAL_PRODUCT_FACT_LEDGER_V1"),"identity":("report/canonical_identity_store.json","CANONICAL_IDENTITY_STORE_V1"),"identity_relationships":("report/canonical_identity_relationships.json","CANONICAL_IDENTITY_RELATIONSHIPS_V1"),"classification_standard":("report/canonical_product_classification.json","CANONICAL_PRODUCT_CLASSIFICATION_V1:STANDARD_SCOPE"),"classification_subtype":("report/canonical_product_classification.json","CANONICAL_PRODUCT_CLASSIFICATION_V1:PRODUCT_SUBTYPE"),"structure":("report/report_standard_structure_compatibility.json","REPORT_STRUCTURE_COMPATIBILITY"),"applicability":("report/canonical_applicability_result.json","CANONICAL_APPLICABILITY_RESULT_V1"),"evidence":("report/canonical_evidence_sufficiency.json","CANONICAL_EVIDENCE_SUFFICIENCY_V1"),"technical":("report/canonical_technical_authority.json","CANONICAL_TECHNICAL_AUTHORITY_V1"),"requirement_state":("decisions/canonical_requirement_state_store.json","CANONICAL_REQUIREMENT_STATE_STORE_V1"),"root":("report/canonical_root_cause_authority.json","CANONICAL_ROOT_CAUSE_AUTHORITY_V1"),"na":("report/canonical_na_authority.json","CANONICAL_NA_AUTHORITY_V1"),"relevance":("report/canonical_product_relevance.json","CANONICAL_PRODUCT_RELEVANCE_V1"),"metrics":("report/canonical_compliance_metrics.json","CANONICAL_COMPLIANCE_METRICS_V1")}
PARENTS={"facts":["report_evidence"],"identity":["report_evidence"],"identity_relationships":["identity"],"classification_standard":["standard_kb","facts","identity"],"classification_subtype":["standard_kb","facts","identity"],"structure":["standard_kb","report_evidence"],"applicability":["standard_kb","facts","classification_standard","classification_subtype"],"evidence":["report_evidence","identity_relationships","structure","applicability"],"technical":["facts","applicability","evidence"],"requirement_state":["applicability","evidence","technical"],"root":["classification_standard","classification_subtype","applicability","evidence","technical","requirement_state","structure"],"na":["applicability","report_evidence"],"relevance":["classification_standard","classification_subtype","facts","applicability"],"metrics":["classification_standard","classification_subtype","facts","identity","applicability","evidence","technical","requirement_state","root","na","relevance","structure"]}
PRODUCERS={k:"GenericCanonical"+"".join(x.title() for x in k.split("_")) for k in ARTIFACTS}
DIAGNOSTICS=("MISSING_DEPENDENCY_EDGE","DANGLING_DEPENDENCY","DEPENDENCY_HASH_MISMATCH","DEPENDENCY_VERSION_MISMATCH","STALE_ARTIFACT_MARKED_CURRENT","CURRENT_ARTIFACT_WITH_STALE_PARENT","REQUIRED_PARENT_MISSING","CIRCULAR_DEPENDENCY","INVALID_RECOMPUTE_ORDER","DEPENDENT_NODE_NOT_INVALIDATED","UNRELATED_NODE_INVALIDATED","TARGETED_RERUN_HASH_MISMATCH","FULL_RERUN_EQUIVALENCE_FAILURE","NON_DETERMINISTIC_FINGERPRINT","NON_DETERMINISTIC_OUTPUT_HASH","UNSTABLE_FIELD_INCLUDED_IN_SEMANTIC_HASH","LEGACY_DEPENDENCY_OVERRIDE","STALE_DEPENDENCY_CONTRACT","SOURCE_TRACE_MISSING")

class StaleCanonicalDependencyError(RuntimeError):pass
class GenericCanonicalDependencyAuthority:
 def build(self,family_id,artifacts):
  content={k:self._select(k,artifacts[k]) for k in ARTIFACTS if k in artifacts};nodes=[]
  hashes={k:self.semantic_hash(v) for k,v in content.items()}
  for k in self.topological_order(content):
   deps=[]
   for p in PARENTS.get(k,[]):
    if p in content:deps.append({"dependency_id":self.node_id(family_id,p),"artifact_type":p,"content_hash":hashes[p],"contract_version":ARTIFACTS[p][1],"reason_code":self._reason(p,k)})
   source=artifacts[k];reqs=self._requirements(source);fingerprint=self.semantic_hash({"dependencies":deps,"producer":PRODUCERS[k],"policy":DEPENDENCY_POLICY,"requirement_ids":reqs})
   nodes.append({"node_id":self.node_id(family_id,k),"artifact_type":k,"family_id":family_id,"contract_version":ARTIFACTS[k][1],"input_dependencies":deps,"input_fingerprint":fingerprint,"output_hash":hashes[k],"producer":PRODUCERS[k],"producer_policy_version":self._policy(source),"status":"CURRENT","reason_codes":[],"requirement_ids":reqs,"source_path":ARTIFACTS[k][0]})
  edges=[{"family_id":family_id,"source_node":d["dependency_id"],"target_node":n["node_id"],"requirement_ids":n["requirement_ids"],"reason":d["reason_code"]} for n in nodes for d in n["input_dependencies"]]
  out={"schema_version":SCHEMA_VERSION,"dependency_policy_version":DEPENDENCY_POLICY,"invalidation_policy_version":INVALIDATION_POLICY,"recompute_policy_version":RECOMPUTE_POLICY,"family_id":family_id,"nodes":nodes,"edges":edges,"summary":{"dependency_nodes":len(nodes),"dependency_edges":len(edges),"current_nodes":len(nodes),"stale_nodes":0,"invalid_nodes":0}};out["manifest_hash"]=self.semantic_hash(out);return out
 def detect(self,manifest,changes):
  out=copy.deepcopy(manifest);by={n["node_id"]:n for n in out["nodes"]};changed=set()
  for key,value in changes.items():
   nid=key if key in by else self.node_id(out["family_id"],key)
   if nid in by and (value.get("content_hash",by[nid]["output_hash"])!=by[nid]["output_hash"] or value.get("contract_version",by[nid]["contract_version"])!=by[nid]["contract_version"] or value.get("producer_policy_version",by[nid].get("producer_policy_version"))!=by[nid].get("producer_policy_version")):changed.add(nid);by[nid]["status"]="STALE";by[nid]["reason_codes"]=["SEMANTIC_DEPENDENCY_CHANGED"]
  children=defaultdict(list)
  for e in out["edges"]:children[e["source_node"]].append(e["target_node"])
  q=deque(changed)
  while q:
   p=q.popleft()
   for c in children[p]:
    if c not in changed:changed.add(c);by[c]["status"]="NEEDS_RECOMPUTE";by[c]["reason_codes"]=["UPSTREAM_DEPENDENCY_STALE"];q.append(c)
  out["summary"].update({"current_nodes":sum(n["status"]=="CURRENT" for n in out["nodes"]),"stale_nodes":sum(n["status"] in {"STALE","NEEDS_RECOMPUTE"} for n in out["nodes"]),"invalid_nodes":sum(n["status"]=="INVALID" for n in out["nodes"])});return out
 def recompute_plan(self,manifest):
  stale={n["artifact_type"] for n in manifest["nodes"] if n["status"]!="CURRENT"};order=[x for x in self.topological_order({n["artifact_type"]:1 for n in manifest["nodes"]}) if x in stale];return {"schema_version":"CANONICAL_RECOMPUTE_PLAN_V1","family_id":manifest["family_id"],"changed_nodes":[n["node_id"] for n in manifest["nodes"] if n["status"]=="STALE"],"stale_nodes":[n["node_id"] for n in manifest["nodes"] if n["status"]!="CURRENT"],"recompute_order":order,"unaffected_nodes":[n["node_id"] for n in manifest["nodes"] if n["status"]=="CURRENT"],"reason_codes":["MINIMAL_TRANSITIVE_INVALIDATION"],"status":"READY" if stale else "NO_CHANGES"}
 def refresh(self,manifest,artifacts):
  fresh=self.build(manifest["family_id"],artifacts);return fresh,{"targeted_hash":fresh["manifest_hash"],"full_rerun_hash":self.build(manifest["family_id"],artifacts)["manifest_hash"],"hash_match":fresh["manifest_hash"]==self.build(manifest["family_id"],artifacts)["manifest_hash"]}
 def assert_current(self,manifest,artifact_type):
  n=next(x for x in manifest["nodes"] if x["artifact_type"]==artifact_type)
  if n["status"]!="CURRENT":raise StaleCanonicalDependencyError(f"{artifact_type} is {n['status']}")
  return True
 def validate(self,m):
  ds=[];by={x["node_id"]:x for x in m.get("nodes",[])};edges={(x["source_node"],x["target_node"]) for x in m.get("edges",[])}
  def add(c,node=None):ds.append({"code":c,"node_id":node})
  for n in m.get("nodes",[]):
   if n["status"] not in STATES:add("STALE_ARTIFACT_MARKED_CURRENT",n["node_id"])
   if not n.get("output_hash") or not n.get("input_fingerprint"):add("SOURCE_TRACE_MISSING",n["node_id"])
   for p in PARENTS.get(n["artifact_type"],[]):
    pid=self.node_id(m["family_id"],p)
    if pid not in by:add("REQUIRED_PARENT_MISSING",n["node_id"])
    elif (pid,n["node_id"]) not in edges:add("MISSING_DEPENDENCY_EDGE",n["node_id"])
   if n["status"]=="CURRENT" and any(by.get(d["dependency_id"],{}).get("status")!="CURRENT" for d in n["input_dependencies"]):add("CURRENT_ARTIFACT_WITH_STALE_PARENT",n["node_id"])
  for a,b in edges:
   if a not in by or b not in by:add("DANGLING_DEPENDENCY",b)
  try:self.topological_order({n["artifact_type"]:1 for n in m.get("nodes",[])})
  except ValueError:add("CIRCULAR_DEPENDENCY")
  c=Counter(x["code"] for x in ds);return {"schema_version":INTEGRITY_SCHEMA,"policy_version":DEPENDENCY_POLICY,"valid":not ds,"total_errors":len(ds),"diagnostic_counts":{x:c[x] for x in DIAGNOSTICS},"diagnostics":ds}
 def topological_order(self,available):
  keys=set(available);ind={k:0 for k in keys};children=defaultdict(list)
  for k in keys:
   for p in PARENTS.get(k,[]):
    if p in keys:ind[k]+=1;children[p].append(k)
  q=deque(sorted(k for k,v in ind.items() if not v));out=[]
  while q:
   x=q.popleft();out.append(x)
   for y in sorted(children[x]):ind[y]-=1;q.append(y) if ind[y]==0 else None
  if len(out)!=len(keys):raise ValueError("circular dependency")
  return out
 @classmethod
 def semantic_content(cls,v):
  if isinstance(v,dict):return {k:cls.semantic_content(x) for k,x in sorted(v.items()) if k.lower() not in UNSTABLE and not k.lower().endswith("_timestamp")}
  if isinstance(v,list):return [cls.semantic_content(x) for x in v]
  return getattr(v,"value",v)
 @classmethod
 def semantic_hash(cls,v):return hashlib.sha256(json.dumps(cls.semantic_content(v),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
 @staticmethod
 def node_id(family,k):return "DEPENDENCY-"+hashlib.sha256(f"{family}|{k}".encode()).hexdigest()[:20].upper()
 @staticmethod
 def _select(k,v):
  if k=="classification_standard":return v.get("standard_scope",{})
  if k=="classification_subtype":return v.get("product_subtype",{})
  return v
 @staticmethod
 def _requirements(v):
  rows=v.get("records") or v.get("results") or v.get("facts") or []
  return sorted({str(x.get("requirement_id") or x.get("effective_requirement_id")) for x in rows if x.get("requirement_id") or x.get("effective_requirement_id")})
 @staticmethod
 def _policy(v):return v.get("policy_version") or v.get("state_policy_version") or v.get("dependency_policy_version") or "SOURCE_POLICY"
 @staticmethod
 def _reason(p,k):return f"{p.upper()}_DEPENDENCY"
 @staticmethod
 def save_json(v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True,indent=2)+"\n");return p
