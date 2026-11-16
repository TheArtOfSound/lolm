/* Bounded syntactic observations from one GitHub Actions YAML workflow.
 * This is NOT a YAML interpreter or vulnerability scanner. Unsupported or
 * ambiguous syntax must produce unknown, never a claim of effective policy.
 * No workflow content, variable values, or secret names are returned.
 */
const ACTION=/^\s*(?:-\s*)?uses:\s*['"]?([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_./-]+)?)@([A-Za-z0-9_.-]{1,128})['"]?(?:\s*(?:#.*)?)?$/;
const SSH=/(^|[^A-Za-z0-9_-])ssh-keyscan(?:[ \t]|$)/;
const SCOPE=/^([a-z][a-z-]{1,40}):\s*(read|write|none)\s*(?:#.*)?$/;
const VALID_PERMISSION_SCOPES=new Set([
 "actions","artifact-metadata","attestations","checks","code-quality","contents",
 "copilot-requests","deployments","discussions","id-token","issues","packages",
 "pages","pull-requests","security-events","statuses","vulnerability-alerts"
]);
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
   if(!clean||pad>literalIndent)
    return {text:"",shell:clean.startsWith("#")?"":clean,pad,line:number};
   literalIndent=-1;
  }
  if(!clean||clean.startsWith("#"))return {text:"",pad,line:number};
  if(/:\s*[|>][+-]?[1-9]?\s*(?:#.*)?$/.test(raw))literalIndent=pad;
  return {text:raw.slice(pad),pad,line:number};
 });
}
// A "uses" key only invokes an action as a job-level reusable workflow or
// as a step of a recognized job. Keys nested under env/with/outputs are data.
function parentRow(rows,index){
 const pad=rows[index].pad;
 for(let i=index-1;i>=0;i--)if(rows[i].text&&rows[i].pad<pad)return i;
 return -1;
}
function isJobRow(rows,index){
 if(index<0||!/^[A-Za-z0-9_-]+:\s*(?:#.*)?$/.test(rows[index].text))return false;
 const parent=parentRow(rows,index);
 return parent>=0&&rows[parent].pad===0&&/^jobs:\s*(?:#.*)?$/.test(rows[parent].text);
}
function actionLocation(rows,index){
 const row=rows[index],parent=parentRow(rows,index);
 if(parent<0)return false;
 const sequence=/^-\s+uses:/.test(row.text);
 // A job can invoke an external reusable workflow directly.
 if(!sequence&&isJobRow(rows,parent))return true;
 const steps=sequence?parent:parentRow(rows,parent);
 if(steps<0||!/^steps:\s*(?:#.*)?$/.test(rows[steps].text))return false;
 if(!isJobRow(rows,parentRow(rows,steps)))return false;
 return sequence||/^-[ \t]+[A-Za-z_][A-Za-z0-9_-]*:/.test(rows[parent].text);
}
// Only GitHub Actions root permissions and direct per-job permissions count.
// An arbitrary nested key named "permissions" (env, with, a step, etc.) is
// not authoritative. Ambiguous nesting is reported unknown.
function permissionsLocation(rows,index){
 const row=rows[index];
 if(row.pad===0)return true;
 if(row.pad!==4)return false;
 let jobs=false,job=false;
 for(let i=0;i<index;i++){
  const x=rows[i];
  if(!x.text)continue;
  if(x.pad===0){
   jobs=/^jobs:\s*(?:#.*)?$/.test(x.text);
   job=false;
  }else if(jobs&&x.pad===2){
   job=/^[A-Za-z0-9_-]+:\s*(?:#.*)?$/.test(x.text);
  }
 }
 return jobs&&job;
}
function permissionDeclarations(rows){
 const found=rows.flatMap((r,i)=>r.text.match(ANY_PERM)?[i]:[]);
 if(!found.length)return {restricted:"unknown",write:"unknown",line:null,writeScopes:[]};
 const indices=found.filter(i=>permissionsLocation(rows,i));
 let sawUnknown=indices.length!==found.length;
 if(!indices.length)return {restricted:"unknown",write:"unknown",line:null,writeScopes:[]};
 let sawWrite=false,first=rows[indices[0]].line,writeScopes=[];
 for(const i of indices){
  const head=rows[i],value=head.text.match(ANY_PERM)?.[1]?.trim()??"";
  if(value==="read-all"||value==="{}")continue;
  if(value==="write-all"){sawWrite=true;first=head.line;
   writeScopes.push({scope:"write-all",line:head.line});continue}
  if(value!==""){sawUnknown=true;continue}
  let count=0;
  for(let j=i+1;j<rows.length;j++){
   const row=rows[j];
   if(!row.text)continue;
   if(row.pad<=head.pad)break;
   if(row.pad!==head.pad+2){sawUnknown=true;continue}
   const m=SCOPE.exec(row.text);
   if(!m||!VALID_PERMISSION_SCOPES.has(m[1])||
      (m[2]==="write"&&m[1]==="vulnerability-alerts")){sawUnknown=true;continue}
   count++;
   if(m[2]==="write"){sawWrite=true;first=row.line;
    writeScopes.push({scope:m[1],line:row.line});}
  }
  if(!count)sawUnknown=true;
 }
 return {restricted:sawWrite?false:sawUnknown?"unknown":true,
  write:sawWrite?true:sawUnknown?"unknown":false,line:first,
  writeScopes:writeScopes.sort((a,b)=>a.line-b.line||a.scope.localeCompare(b.scope)).slice(0,36)};
}
function triggerDeclaration(rows){
 const headers=rows.filter(r=>r.pad===0&&TOP_ON.test(r.text));
 if(headers.length!==1)return {value:"unknown",line:null};
 const header=headers[0],inline=TOP_ON.exec(header.text)[1].trim();
 if(inline){
  if(/^[A-Za-z][A-Za-z0-9_-]*$/.test(inline))
   return {value:inline==="pull_request_target",line:inline==="pull_request_target"?header.line:null};
  if(/^\[[^\]{}]*\]$/.test(inline)){
   const items=inline.slice(1,-1).split(",").map(s=>s.trim());
   if(!items.length||items.some(x=>!/^[A-Za-z][A-Za-z0-9_-]*$/.test(x)))
    return {value:"unknown",line:null};
   return {value:items.includes("pull_request_target"),line:items.includes("pull_request_target")?header.line:null};
  }
  // Inline YAML maps, aliases and expressions need real YAML parsing.
  return {value:"unknown",line:null};
 }
 let sawEvent=false,unclear=false,matchLine=null;
 for(const r of rows){
  if(r.line<=header.line||!r.text)continue;
  if(r.pad===0)break;
  if(r.pad!==2)continue;
  const mapping=/^([A-Za-z][A-Za-z0-9_-]*):(?:\s|$)/.exec(r.text);
  const sequence=/^-\s+([A-Za-z][A-Za-z0-9_-]*)\s*(?:#.*)?$/.exec(r.text);
  const event=mapping?.[1]||sequence?.[1];
  if(!event){unclear=true;continue}
  sawEvent=true;
  if(event==="pull_request_target")matchLine=r.line;
 }
 if(matchLine)return {value:true,line:matchLine};
 return {value:sawEvent&&!unclear?false:"unknown",line:null};
}
export function scanWorkflowSyntax(text){
 const rows=activeLines(text);
 const mutable=[],ssh=[];
 for(let i=0;i<rows.length;i++){
  const r=rows[i];
  if(!r.text&&!r.shell)continue;
  const action=r.text?ACTION.exec(r.text):null;
  if(action&&actionLocation(rows,i)&&!/^[a-fA-F0-9]{40}$/.test(action[2]))mutable.push(r.line);
  // Shell blocks are not YAML declarations, but can contain the SSH command.
  if(SSH.test(r.shell||r.text))ssh.push(r.line);
 }
 const permissions=permissionDeclarations(rows);
 const target=triggerDeclaration(rows);
 return {
  runtime_ssh_keyscan:{value:ssh.length>0,line:ssh[0]??null},
  workflow_unpinned_actions:{value:mutable.length>0,line:mutable[0]??null},
  workflow_explicit_read_only_permissions:{value:permissions.restricted,line:permissions.line},
  workflow_token_write_permission:{value:permissions.write,line:permissions.line},
  workflow_pull_request_target_trigger:target,
  writeScopes:permissions.writeScopes
 };
}
