"""Derive standard test steps and report rows from stored structured evidence."""
from __future__ import annotations
import copy,hashlib,json,re
from collections import Counter,defaultdict
from dataclasses import asdict,is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any,Dict,List,Mapping,Optional,Sequence,Tuple
from .generic_test_structure_models import *

class GenericTestStructureEnricher:
 _CUES=[(StandardTestStepType.POST_TEST_CHECK,r"\b(after|following)\s+the\s+test\b"),(StandardTestStepType.ACCEPTANCE_CHECK,r"\bshall\s+not\s+(exceed|be greater)|\bshall withstand\b|\bthere shall be no\b|\bshall comply\b"),(StandardTestStepType.REPEAT,r"\brepeat(?:ed)?\b|\bcycles?\b"),(StandardTestStepType.MEASURE,r"\bmeasur(?:e|ed|ement)\b|\btemperature rise\b|\bleakage current\b"),(StandardTestStepType.WAIT,r"\bfor\s+\d+(?:[.,]\d+)?\s*(s|sec|seconds?|min|minutes?|h|hours?)\b|\bafter\s+\d+"),(StandardTestStepType.APPLY_INPUT,r"\bsupplied at\b|\bvoltage is applied\b|\bforce is applied\b|\bcurrent is\b"),(StandardTestStepType.OPERATE,r"\boperat(?:e|ed|ing)\b|\brun\b|\bstarted\b"),(StandardTestStepType.SETUP,r"\bmounted\b|\bfilled\b|\bconnected\b|\bloaded\b|\bplaced\b"),(StandardTestStepType.PRECONDITION,r"\bbefore the test\b|\bunder normal operation\b|\bwith controls set\b"),(StandardTestStepType.RESET,r"\breset\b|\brestored\b"),(StandardTestStepType.OBSERVE,r"\bobserv(?:e|ed|ation)\b")]
 _PARAM=[("temperature rise","TEMPERATURE_RISE","TEST_TEMPERATURE"),("leakage current","CURRENT","TEST_CURRENT"),("test voltage","VOLTAGE","TEST_VOLTAGE"),("applied voltage","VOLTAGE","TEST_VOLTAGE"),("voltage","VOLTAGE","TEST_VOLTAGE"),("duration","TIME","TEST_DURATION"),("speed","SPEED","TEST_SPEED"),("force","FORCE","TEST_FORCE"),("load","GENERIC_NUMERIC","TEST_LOAD"),("flow","FLOW_RATE","TEST_FLOW"),("cycles","COUNT","TEST_CYCLE_COUNT"),("temperature","TEMPERATURE","TEST_TEMPERATURE"),("distance","DISTANCE","TEST_DISTANCE"),("opening","DISTANCE","TEST_DISTANCE"),("current","CURRENT","TEST_CURRENT"),("power","POWER","TEST_POWER")]
 def enrich(self,effective_kb,report_evidence,grouping,evidence_scope,product_profile,evidence_enrichment,integrity_result):
  diagnostics=[];reqs=self._requirements(effective_kb);conditions=self._by(self._get(evidence_enrichment,"required_test_conditions",[]) or [],"effective_requirement_id");standard=self._standard(grouping,reqs,conditions,diagnostics);scope={str(self._get(x,"report_evidence_id")):x for x in self._get(evidence_scope,"results",[]) or []};actual=self._by(self._get(evidence_enrichment,"actual_test_conditions",[]) or [],"report_evidence_id");calcs=self._by(self._get(evidence_enrichment,"calculations",[]) or [],"report_evidence_id");report,rowscope=self._report(report_evidence,scope,actual,calcs,diagnostics);links=self._links(standard,report,rowscope,diagnostics);summary=self._summary(standard,report,links,rowscope);identity=self._get(product_profile,"identity",{}) or {}
  if not self._get(identity,"serial_numbers",[]) and not self._get(identity,"sample_identifiers",[]):diagnostics.append({"code":"STRUCTURE_SAMPLE_IDENTITY_NOT_PRESENT"})
  return TestStructureEnrichmentReport(str(self._get(effective_kb,"effective_kb_id","") or ""),str(self._get(report_evidence,"document_id","") or ""),standard,report,links,rowscope,summary,sorted(diagnostics,key=lambda x:json.dumps(x,sort_keys=True)))
 def _standard(self,grouping,reqs,conditions,diagnostics):
  out=[]
  for group in self._get(grouping,"groups",[]) or []:
   gid=str(self._get(group,"group_id"));members=self._get(group,"members",[]) or [];active=[m for m in members if str(self._get(reqs.get(str(self._get(m,"effective_requirement_id")),{}),"effective_status","ACTIVE"))!="INACTIVE"]
   primary=str(self._get(group,"primary_requirement_id","") or "");clause=self._get(group,"clause_id");steps=[];accept=[];post=[];exceptions=[];measure=[];required=[];provs=[];order=0
   for member in sorted(active,key=lambda x:int(self._get(x,"source_order",0) or 0)):
    rid=str(self._get(member,"effective_requirement_id"));req=reqs.get(rid,{});text=str(self._get(req,"text","") or "");role=str(self._get(member,"role","") or "");prov=StructureProvenance("effective_kb",rid,clause,rid,gid,None,None,text[:500]);provs.append(prov)
    segments=self._segments(text)
    for segment in segments:
     order+=1;stype=self._step_type(segment,role);ptype,crole=self._parameter(segment);value,unit=self._numeric(segment);refs=self._references(segment);status=StructureStatus.RESOLVED if stype!=StandardTestStepType.OTHER else StructureStatus.NEEDS_REVIEW;step=StandardTestStep(self._id("STD-STEP",gid,rid,str(order),segment),order,stype,segment,ptype,crole,None,value,unit,refs,status,[prov]);steps.append(step)
     if stype==StandardTestStepType.ACCEPTANCE_CHECK or role=="ACCEPTANCE_CRITERION":accept.append(step.step_id)
     if stype==StandardTestStepType.POST_TEST_CHECK or role=="POST_TEST_CONDITION":post.append(step.step_id)
     if role=="EXCEPTION":exceptions.append(step.step_id)
     if stype==StandardTestStepType.MEASURE:measure.append(step.step_id)
    for c in conditions.get(rid,[]):required.append(str(self._get(c,"condition_id")))
   if not steps:diagnostics.append({"code":"STRUCTURE_STANDARD_TEST_METHOD_MISSING","group_id":gid})
   unresolved=sum(x.status!=StructureStatus.RESOLVED for x in steps)
   if unresolved:diagnostics.append({"code":"STRUCTURE_STANDARD_TEST_STEP_UNRESOLVED","group_id":gid,"count":unresolved})
   status=StructureStatus.RESOLVED if steps and not unresolved else StructureStatus.NEEDS_REVIEW if steps else StructureStatus.UNRESOLVED;out.append(StandardTestStructure(self._id("STD-STRUCT",gid),"STANDARD",clause,gid,primary or None,[str(self._get(x,"effective_requirement_id")) for x in active],self._get(reqs.get(primary,{}),"text"),steps,required,measure,accept,post,exceptions,min([int(self._get(x,"source_order",0) or 0) for x in active] or [0]),status,1.0 if status==StructureStatus.RESOLVED else .65,provs))
  return sorted(out,key=lambda x:(x.clause_id or "",x.group_id))
 def _report(self,report,scope,actual,calcs,diagnostics):
  structures=[];scope_rows=[]
  for clause in self._walk_clauses(self._get(report,"clauses",[]) or []):
   cid=str(self._get(clause,"clause_id"));rows=[];row_order=0
   for evidence in self._get(clause,"evidence_items",[]) or []:
    eid=str(self._get(evidence,"evidence_id"));raw=str(self._get(evidence,"raw_text","") or "");verdict=self._get(evidence,"reported_verdict");segments=self._report_segments(raw);parent=None
    if len(segments)>1 and not self._line_verdicts(segments):segments=[raw];diagnostics.append({"code":"STRUCTURE_REPORT_VERDICT_OWNERSHIP_AMBIGUOUS","evidence_id":eid})
    for i,segment in enumerate(segments):
     row_order+=1;level=self._row_level(segment,evidence);row_id=self._id("REPORT-ROW",eid,str(i));owned_measure=[]
     for m in self._get(evidence,"measurements",[]) or []:
      mraw=str(self._get(m,"raw_text","") or "");label=str(self._get(m,"parameter_text",self._get(m,"parameter","")) or "")
      if len(segments)==1 or (mraw and mraw in segment) or (label and label.casefold() in segment.casefold()):owned_measure.append(str(self._get(m,"measurement_id")))
     if self._get(evidence,"measurements",[]) and not owned_measure:diagnostics.append({"code":"STRUCTURE_REPORT_MEASUREMENT_OWNERSHIP_AMBIGUOUS","evidence_id":eid})
     owned_actual=[str(self._get(x,"condition_id")) for x in actual.get(eid,[]) if len(segments)==1 or str(self._get(self._get(x,"observed_value",{}),"raw_text","") or "") in segment]
     if actual.get(eid) and not owned_actual:diagnostics.append({"code":"STRUCTURE_REPORT_CONDITION_OWNERSHIP_AMBIGUOUS","evidence_id":eid})
     calc_refs=[str(self._get(x,"calculation_id")) for x in calcs.get(eid,[]) if len(segments)==1 or str(self._get(self._get(x,"reported_expression",{}),"raw_expression","") or "") in segment]
     remarks=[]
     for remark in self._get(evidence,"remarks",[]) or []:remarks.append(str(remark))
     label=self._label(segment);row_verdict=self._extract_verdict(segment) if len(segments)>1 else verdict;prov=StructureProvenance("report_evidence",eid,cid,None,None,self._get(evidence,"page_start"),self._get(evidence,"page_end"),segment[:500]);rows.append(ReportResultRow(row_id,row_order,parent,level,label,segment if level not in {ReportRowLevel.MEASUREMENT_ROW,ReportRowLevel.REMARK_ROW} else None,segment if self._procedure(segment) else None,owned_actual,owned_measure,calc_refs,remarks,row_verdict,segment,StructureStatus.RESOLVED if segment.strip() else StructureStatus.UNRESOLVED,[prov]));s=scope.get(eid,{});outer=self._enum(self._get(s,"scope_status"));candidates=self._group_ids(self._get(s,"candidate_groups",[]) or []);selected=self._group_ids(self._get(s,"selected_groups",[]) or []);narrow=selected if outer in {"EXACT_GROUP","MULTIPLE_GROUPS"} else [];scope_status=StructureLinkStatus.MATCHED if len(narrow)==1 else StructureLinkStatus.POSSIBLE if narrow else StructureLinkStatus.AMBIGUOUS if outer=="AMBIGUOUS" else StructureLinkStatus.NO_MATCH;scope_rows.append(RowScopeCandidate(row_id,eid,outer,candidates,narrow,scope_status,"Derived within the existing clause-level scope boundary."))
   if not rows:diagnostics.append({"code":"STRUCTURE_REPORT_ROW_UNRESOLVED","clause_id":cid})
   structures.append(ReportClauseStructure(self._id("REPORT-STRUCT",cid),"REPORT",cid,self._get(clause,"page_start"),self._get(clause,"page_end"),rows,StructureStatus.RESOLVED if rows else StructureStatus.UNRESOLVED,[StructureProvenance("report_evidence",self._get(clause,"result_id"),cid,page_start=self._get(clause,"page_start"),page_end=self._get(clause,"page_end"),raw_excerpt=str(self._get(clause,"raw_text","") or "")[:500])]))
  return structures,scope_rows
 def _links(self,standard,report,row_scopes,diagnostics):
  scope={x.row_id:x for x in row_scopes};links=[];row_items=[(s,r) for s in report for r in s.rows]
  for std in standard:
   procedural=[x for x in std.test_method_steps if x.parameter_type and x.step_type in {StandardTestStepType.APPLY_INPUT,StandardTestStepType.WAIT,StandardTestStepType.MEASURE,StandardTestStepType.OPERATE,StandardTestStepType.REPEAT,StandardTestStepType.SETUP}]
   for step in procedural:
    candidates=[]
    for rs,row in row_items:
     ptype,crole=self._parameter(row.raw_text or "");param=ptype==step.parameter_type;role=crole==step.condition_role or step.condition_role is None or crole is None;sc=scope.get(row.row_id);scope_ok=bool(sc and std.group_id in sc.narrowed_group_ids);text=self._overlap(step.text,row.raw_text or "");order=step.step_order==row.row_order;confidence=.4*scope_ok+.25*param+.15*role+.15*text+.05*order
     clause_ok=self._clause_related(std.clause_id,rs.report_clause_id)
     if scope_ok or (param and clause_ok):candidates.append((rs,row,param,role,scope_ok,text,order,confidence))
    strong=[x for x in candidates if x[2] and x[3] and x[4] and x[7]>=.75]
    for rs,row,param,role,scope_ok,text,order,confidence in candidates:
     status=StructureLinkStatus.MATCHED if (rs,row,param,role,scope_ok,text,order,confidence) in strong and len(strong)==1 else StructureLinkStatus.AMBIGUOUS if len(strong)>1 else StructureLinkStatus.POSSIBLE if param or scope_ok else StructureLinkStatus.NO_MATCH
     links.append(TestStructureLinkCandidate(self._id("STRUCT-LINK",std.structure_id,step.step_id,row.row_id),std.structure_id,[step.step_id],rs.structure_id,[row.row_id],std.group_id,std.clause_id,param,role,text,scope_ok,order,status,"Structural candidate uses existing scope, semantic parameter, role, text, and order.",round(confidence,6)))
   if procedural and not any(x.standard_structure_id==std.structure_id for x in links):diagnostics.append({"code":"STRUCTURE_LINK_PARAMETER_MISMATCH","group_id":std.group_id})
  matched_rows=Counter(row for x in links if x.candidate_status==StructureLinkStatus.MATCHED for row in x.report_row_ids)
  for x in links:
   if x.candidate_status==StructureLinkStatus.MATCHED and any(matched_rows[row]>1 for row in x.report_row_ids):x.candidate_status=StructureLinkStatus.AMBIGUOUS;x.reason="Multiple standard steps compete for the same structurally owned report row.";diagnostics.append({"code":"STRUCTURE_LINK_MULTIPLE_CANDIDATES","link_id":x.link_id})
  return sorted(links,key=lambda x:x.link_id)
 @staticmethod
 def _clause_related(left,right):
  a=str(left or "");b=str(right or "");return a==b or a.startswith(b+".") or b.startswith(a+".")
 @classmethod
 def _segments(cls,text):
  parts=[x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z])|\n+",text or "") if x.strip()];out=[]
  for part in parts:
   m=re.search(r"\s+(for\s+\d+(?:[.,]\d+)?\s*(?:s|sec|seconds?|min|minutes?|h|hours?)\b)",part,re.I)
   if m and re.search(r"\b(applied|supplied|operated|force|voltage|current)\b",part[:m.start()],re.I):out.extend([part[:m.start()].strip(),m.group(1).strip()+("." if part.endswith(".") else "")])
   else:out.append(part)
  return out or ([text.strip()] if text and text.strip() else [])
 @classmethod
 def _step_type(cls,text,role=""):
  if role=="ACCEPTANCE_CRITERION":return StandardTestStepType.ACCEPTANCE_CHECK
  if role=="POST_TEST_CONDITION":return StandardTestStepType.POST_TEST_CHECK
  for t,p in cls._CUES:
   if re.search(p,text,re.I):return t
  return StandardTestStepType.OTHER
 @classmethod
 def _parameter(cls,text):
  s=str(text or "").casefold()
  for cue,p,r in cls._PARAM:
   if cue in s:return p,r
  return None,None
 @staticmethod
 def _numeric(text):
  m=re.search(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(mA|A|mV|kV|V|kW|W|Hz|°C|K|s|min|h|mm|cm|m|r/min|N|cycles|%)\b",text,re.I);return ((float(m.group(1).replace(",",".")) if "." in m.group(1) or "," in m.group(1) else int(m.group(1))),m.group(2)) if m else (None,None)
 @staticmethod
 def _references(text):return re.findall(r"\b(?:Clause|Table|Figure|test of)\s+[A-Za-z0-9.-]+",text,re.I)
 @staticmethod
 def _report_segments(raw):return [x.strip() for x in str(raw or "").splitlines() if x.strip()]
 @staticmethod
 def _line_verdicts(lines):return sum(bool(re.search(r"(?:\.{2,}|\s)(P|PASS|F|FAIL|N/?A)\s*$",x,re.I)) for x in lines)>=2
 @staticmethod
 def _extract_verdict(line):
  m=re.search(r"(?:\.{2,}|\s)(P|PASS|F|FAIL|N/?A)\s*$",line,re.I);return {"P":"PASS","F":"FAIL","N/A":"NA","NA":"NA"}.get(m.group(1).upper(),m.group(1).upper()) if m else None
 @classmethod
 def _row_level(cls,text,evidence):
  if cls._get(evidence,"measurements",[]):return ReportRowLevel.MEASUREMENT_ROW
  if re.match(r"^\s*[-•*]",text):return ReportRowLevel.BULLET
  if re.match(r"^\s*\d+(?:\.\d+)+",text):return ReportRowLevel.SUBROW
  if "|" in text or "\t" in text:return ReportRowLevel.TABLE_ROW
  if re.search(r"\b(remark|note)\s*:",text,re.I):return ReportRowLevel.REMARK_ROW
  return ReportRowLevel.ROW
 @staticmethod
 def _label(text):
  m=re.match(r"\s*([^:]{1,100})\s*:",text);return m.group(1).strip() if m else None
 @staticmethod
 def _procedure(text):return bool(re.search(r"\b(test|tested|applied|operated|duration|measured|cycles?)\b",text,re.I))
 @staticmethod
 def _overlap(a,b):
  stop={"the","and","shall","with","that","this","for","from","are","was","test"};x={w for w in re.findall(r"[a-z0-9]+",a.casefold()) if len(w)>2 and w not in stop};y={w for w in re.findall(r"[a-z0-9]+",b.casefold()) if len(w)>2 and w not in stop};return len(x&y)/len(x|y) if x|y else 0.0
 @classmethod
 def _summary(cls,std,report,links,rowscope):
  steps=[x for s in std for x in s.test_method_steps];rows=[x for s in report for x in s.rows];types=Counter(x.step_type.value for x in steps);levels=Counter(x.row_level.value for x in rows);link=Counter(x.candidate_status.value for x in links)
  return {"standard":{"logical_groups_examined":len(std),"groups_with_test_structure":sum(bool(x.test_method_steps) for x in std),"test_steps_extracted":len(steps),"steps_by_type":{x.value:types[x.value] for x in StandardTestStepType},"required_test_conditions_attached":sum(len(x.required_conditions) for x in std),"acceptance_criteria_separated":sum(len(x.acceptance_criteria) for x in std),"post_test_criteria_separated":sum(len(x.post_test_criteria) for x in std)},"report":{"report_clauses_examined":len(report),"rows_created":len(rows),"subrows_created":levels["SUBROW"],"table_rows_created":levels["TABLE_ROW"],"rows_with_verdict":sum(bool(x.reported_verdict) for x in rows),"rows_with_actual_test_condition":sum(bool(x.actual_conditions) for x in rows),"rows_with_measurement":sum(bool(x.measurements) for x in rows),"rows_with_calculation":sum(bool(x.calculation_refs) for x in rows),"rows_with_remarks":sum(bool(x.remarks) for x in rows)},"linking":{x.value:link[x.value] for x in StructureLinkStatus},"matched_links_by_parameter_role":dict(Counter(next((step.condition_role for s in std for step in s.test_method_steps if step.step_id in x.standard_step_ids),"OTHER") for x in links if x.candidate_status==StructureLinkStatus.MATCHED)),"row_scope_narrowing_candidates":sum(bool(x.narrowed_group_ids) for x in rowscope)}
 @classmethod
 def _requirements(cls,kb):
  out={}
  def walk(nodes):
   for c in nodes:
    for r in cls._get(c,"requirements",[]) or []:out[str(cls._get(r,"effective_requirement_id",cls._get(r,"requirement_id")))]=r
    walk(cls._get(c,"children",[]) or [])
  walk(cls._get(kb,"clauses",[]) or [])
  for a in cls._get(kb,"annexes",[]) or []:
   for r in cls._get(a,"requirements",[]) or []:out[str(cls._get(r,"effective_requirement_id",cls._get(r,"requirement_id")))]=r
  return out
 @classmethod
 def _walk_clauses(cls,nodes):
  for x in nodes:yield x;yield from cls._walk_clauses(cls._get(x,"children",[]) or [])
 @classmethod
 def _by(cls,items,key):
  out=defaultdict(list)
  for x in items:out[str(cls._get(x,key))].append(x)
  return out
 @classmethod
 def _group_ids(cls,items):return [str(cls._get(x,"group_id",x)) for x in items]
 @staticmethod
 def _id(*parts):return parts[0]+"-"+hashlib.sha256("\x1f".join(parts[1:]).encode()).hexdigest()[:18].upper()
 @staticmethod
 def _get(v,n,d=None):return v.get(n,d) if isinstance(v,Mapping) else getattr(v,n,d) if v is not None else d
 @staticmethod
 def _enum(v):return None if v is None else str(v.value if isinstance(v,Enum) else v)
 @classmethod
 def _plain(cls,v):
  if isinstance(v,Enum):return v.value
  if is_dataclass(v):return cls._plain(asdict(v))
  if isinstance(v,dict):return {k:cls._plain(x) for k,x in v.items()}
  if isinstance(v,list):return [cls._plain(x) for x in v]
  return v
 @classmethod
 def to_dict(cls,v):return cls._plain(asdict(v)) if is_dataclass(v) else (_ for _ in ()).throw(TypeError("structure report required"))
 @classmethod
 def to_json(cls,v,indent=2):return json.dumps(cls.to_dict(v),ensure_ascii=False,sort_keys=True,indent=indent)
 @classmethod
 def save_json(cls,v,p):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(cls.to_json(v)+"\n",encoding="utf-8");return p
__all__=["GenericTestStructureEnricher"]
