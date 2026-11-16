/* Bounded syntactic observations from one GitHub Actions YAML workflow.
 * This is NOT a YAML interpreter or vulnerability scanner. Unsupported or
 * ambiguous syntax must produce unknown, never a claim of effective policy.
 * No workflow content, variable values, or secret names are returned.
 */
const ACTION=/^\s*(?:-\s*)?uses:\s*['"]?([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_./-]+)?)@([A-Za-z0-9_.-]{1,128})['"]?(?:\s*(?:#.*)?)?$/;
const SSH=/(^|[^A-Za-z0-9_-])ssh-keyscan(?:[ \t]|$)/;
const SCOPE=/^([a-z][a-z-]{1,40}):\s*(read|write|none)\s*(?:#.*)?$/;
const ANY_PERM=/^permissions:\s*(.*?)\s*$/;
const TOP_ON=/^(?:on|"on"|'on'):\s*(.*?)\s*$/;
const TRIGGER=/(?:^|[,\[\s])pull_request_target(?=$|[,\]\s:#])/;
function indent(raw){const m=/^([ \t]*)/.exec(raw);return m[1].includes("\t")?-1:m[1].length}
function activeLines(text){
 if(typeof text!=="string"||text.length>128000)throw Error("Invalid bounded workflow content");
 let literalIndent=-1;
 return text.replace(/^\uFEFF/,"").split(/\r?\n/).map((raw,i)=>{
  const pad=indent(raw),clean=raw.trim(),number=i+1;
  if(pad<0)return {text:"",pad:-1,line:number};
  if(literalIndent>=0){
   if(!clean||pad>literalIndent)return {text:"",pad,line:number};
   literalIndent=-1;
  }
  if(!clean||clean.startsWith("#"))return {text:"",pad,line:number};
  if(/:\s*[|>][+-]?[1-9]?\s*(?:#.*)?$/.test(raw))literalIndent=pad;
  return {text:raw.slice(pad),pad,line:number};
 });
}
function permissionDeclarations(rows){
 const indices=rows.flatMap((r,i)=>r.text.match(ANY_PERM)?[i]:[]);
 if(!indices.length)return {restricted:"unknown",write:"unknown",line:null};
 let sawWrite=false,sawUnknown=false;
 let first=rows[indices[0]].line;
 for(const i of indices){
  const head=rows[i],value=head.text.match(ANY_PERM)?.[1]?.trim()??"";
  if(value==="read-all"||value==="{}")continue;
  if(value==="write-all"){sawWrite=true;first=head.line;continue}
  if(value!==""){sawUnknown=true;continue}
  let count=0;
  for(let j=i+1;j<rows.length;j++){
   const row=rows[j];if(!row.text)continue;
   if(row.pad<=head.pad)break;
   if(row.pad!==head.pad+2){sawUnknown=true;continue}
   const m=SCOPE.exec(row.text);
   if(!m){sawUnknown=true;continue}
   count++;
   if(m[2]==="write"){sawWrite=true;first=row.line}
  }
  if(!count)sawUnknown=true;
 }
 return {restricted:sawWrite?false:sawUnknown?"unknown":true,
  write:sawWrite?true:sawUnknown?"unknown":false,line:first};
}
function triggerDeclaration(rows){
 const start=rows.findIndex(r=>r.pad===0&&TOP_ON.test(r.text));
 if(start<0)return {value:"unknown",line:null};
 const header=rows[start], inline=TOP_ON.exec(header.text)[1];
 if(inline){
  return {value:TRIGGER.test(inline),line:TRIGGER.test(inline)?header.line:null};
 }
 for(let i=start+1;i<rows.length;i++){
  const r=rows[i];if(!r.text)continue;
  if(r.pad===0)break;
  if(r.pad===2&&/^pull_request_target\s*:/.test(r.text))
   return {value:true,line:r.line};
 }
 return {value:false,line:null};
}
export function scanWorkflowSyntax(text){
 const rows=activeLines(text);
 const mutable=[],ssh=[];
 for(const r of rows){
  if(!r.text)continue;
  const action=ACTION.exec(r.text);
  if(action&&!/^[a-fA-F0-9]{40}$/.test(action[2]))mutable.push(r.line);
  if(SSH.test(r.text))ssh.push(r.line);
 }
 const permissions=permissionDeclarations(rows);
 const target=triggerDeclaration(rows);
 return {
  runtime_ssh_keyscan:{value:ssh.length>0,line:ssh[0]??null},
  workflow_unpinned_actions:{value:mutable.length>0,line:mutable[0]??null},
  workflow_explicit_read_only_permissions:{value:permissions.restricted,line:permissions.line},
  workflow_token_write_permission:{value:permissions.write,line:permissions.line},
  workflow_pull_request_target_trigger:target
 };
}
