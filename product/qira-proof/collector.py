#!/usr/bin/env python3
"""QIRA Proof read-only collector for GitHub and Cloudflare configuration metadata.

Never sends provider tokens or raw content to QIRA services. Uses GET only.
The resulting local snapshot may disclose infrastructure names; store privately.

Requires: GITHUB_TOKEN for GitHub workflow reads,
          CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID for --cloudflare-worker,
          VERCEL_TOKEN for --vercel-project (optional VERCEL_TEAM_ID).
All credentials remain in the local environment and are never exported.
Providers should grant only the required read-only privileges.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCHEMA="qira-proof/snapshot-v1"
GITHUB_RE=re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
WORKER_RE=re.compile(r"^[a-z0-9_][a-z0-9_-]{0,62}$")
ACCOUNT_RE=re.compile(r"^[a-f0-9]{32}$")
VERCEL_PROJECT_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
VERCEL_TEAM_RE=re.compile(r"^team_[A-Za-z0-9_-]{4,100}$")
PRIVILEGED_BINDINGS=frozenset({"secret_text","d1","kv_namespace","r2_bucket","vectorize",
                                "service","hyperdrive","ai_gateway","queue","durable_object_namespace"})

class ProviderError(RuntimeError):
    pass

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def safe_json(data):
    return json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()

def fetch_json(url, token, provider):
    # Only fixed provider origins; never fetch URLs from returned configuration.
    if provider == "github":
        if not url.startswith("https://api.github.com/repos/"):
            raise ProviderError("refusing non-GitHub API endpoint")
        headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
                 "X-GitHub-Api-Version":"2022-11-28","User-Agent":"qira-proof-local-readonly"}
    elif provider == "cloudflare":
        if not url.startswith("https://api.cloudflare.com/client/v4/accounts/"):
            raise ProviderError("refusing non-Cloudflare API endpoint")
        headers={"Authorization":"Bearer "+token,"Accept":"application/json",
                 "User-Agent":"qira-proof-local-readonly"}
    elif provider == "vercel":
        from urllib.parse import urlsplit
        u=urlsplit(url)
        if u.scheme!="https" or u.netloc!="api.vercel.com" or not u.path.startswith(("/v9/projects/","/v6/deployments")):
            raise ProviderError("refusing non-Vercel API endpoint")
        headers={"Authorization":"Bearer "+token,"Accept":"application/json",
                 "User-Agent":"qira-proof-local-readonly"}
    else:
        raise ProviderError("unknown provider")
    try:
        with urlopen(Request(url,headers=headers,method="GET"),timeout=15) as response:
            raw=response.read(1_000_001)
            if len(raw)>1_000_000:
                raise ProviderError("metadata response exceeds 1 MB")
            data=json.loads(raw)
    except HTTPError as e:
        # Never echo headers or provider response bodies: they may contain private data.
        if e.code in (401,403,404):
            raise ProviderError(f"{provider}: metadata unavailable (HTTP {e.code})") from None
        raise ProviderError(f"{provider}: API returned HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        raise ProviderError(f"{provider}: metadata could not be read ({type(e).__name__})") from None
    if provider=="cloudflare":
        if not isinstance(data,dict) or data.get("success") is not True:
            raise ProviderError("Cloudflare API did not confirm success")
        return data["result"]
    if not isinstance(data,dict):
        raise ProviderError(f"{provider} API returned unexpected content")
    return data

def fact(provider,asset,signal,value,url,when):
    if type(value) is not bool and value!="unknown":
        raise ProviderError("fact value must be boolean or unknown")
    return dict(provider=provider,asset=asset,signal=signal,value=value,
                source_url=url,observed_at=when)

def github_facts(repo,workflow,token,reader=fetch_json,when=None):
    if not GITHUB_RE.fullmatch(repo):
        raise ValueError("repository must be owner/name")
    if not workflow.startswith(".github/workflows/") or ".." in workflow or not workflow.endswith((".yaml",".yml")):
        raise ValueError("workflow must be under .github/workflows/")
    when=when or utcnow()
    encoded=quote(workflow,safe="/")
    ref=repo.split("/")
    base=f"https://api.github.com/repos/{ref[0]}/{ref[1]}"
    repository=reader(base,token,"github")
    default_branch=repository.get("default_branch") if isinstance(repository,dict) else None
    if not isinstance(default_branch,str) or not 1 <= len(default_branch) <= 128 or not re.fullmatch(r"[A-Za-z0-9_./-]+",default_branch) or ".." in default_branch:
        raise ProviderError("GitHub default branch could not be verified")
    branch_encoded=quote(default_branch,safe="")
    snapshot=reader(base+"/contents/"+encoded+"?ref="+branch_encoded,token,"github")
    if snapshot.get("encoding")!="base64" or not isinstance(snapshot.get("content"),str):
        raise ProviderError("workflow not available as bounded base64 content")
    text=base64.b64decode(snapshot["content"],validate=False)
    if len(text)>128_000:
        raise ProviderError("workflow file exceeds 128 KB")
    text=text.decode("utf-8")
    active_lines=[x for x in text.splitlines() if not x.lstrip().startswith("#")]
    has_scan=any(re.search(r"(?<![A-Za-z0-9_-])ssh-keyscan(?:[ \t]|$)",line) for line in active_lines)
    # Review-only syntactic test. Only GitHub owner/repo@ref forms; local
    # composite actions and Docker images need separate checks.
    action_ref=re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?)@([A-Za-z0-9_.-]{1,128})['\"]?(?:\s*(?:#.*)?)?$")
    unpinned=any((match:=action_ref.fullmatch(line)) is not None and
                 re.fullmatch(r"[a-fA-F0-9]{40}",match.group(2)) is None
                 for line in active_lines)
    source=f"https://github.com/{repo}/blob/{branch_encoded}/{workflow}"
    facts=[fact("github",repo,"runtime_ssh_keyscan",has_scan,source,when),
           fact("github",repo,"workflow_unpinned_actions",unpinned,source,when)]
    if has_scan:
        # Proving SSH host-key pinning requires authoritative key material and
        # a trusted out-of-band comparison, NOT a string search.
        facts.append(fact("github",repo,"ssh_host_key_pinned","unknown",source,when))
    try:
        reader(base+"/branches/"+branch_encoded+"/protection",token,"github")
        status=True
    except ProviderError:
        status="unknown"
    facts.append(fact("github",repo,"repo_branch_protection_verifiable",status,
                      f"https://github.com/{repo}/settings/branches",when))
    return facts

def cloudflare_facts(account,worker,token,reader=fetch_json,when=None):
    if not ACCOUNT_RE.fullmatch(account) or not WORKER_RE.fullmatch(worker):
        raise ValueError("invalid Cloudflare account ID or Worker name")
    when=when or utcnow()
    base=f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}"
    sub=reader(base+"/subdomain",token,"cloudflare")
    settings=reader(base+"/settings",token,"cloudflare")
    if not isinstance(sub,dict) or not isinstance(settings,dict):
        raise ProviderError("Cloudflare returned invalid metadata")
    if type(sub.get("enabled")) is not bool or type(sub.get("previews_enabled")) is not bool:
        raise ProviderError("Worker subdomain state was not boolean")
    bindings=settings.get("bindings",[])
    if not isinstance(bindings,list) or any(not isinstance(x,dict) or not isinstance(x.get("type"),str) for x in bindings):
        raise ProviderError("Worker bindings metadata unavailable")
    # Intentionally never serialize binding names, text values, secret values,
    # backend endpoint URLs, account keys, API credentials, or source code.
    url=base+"/settings"
    return [
        fact("cloudflare",worker,"worker_preview_enabled",sub["previews_enabled"],base+"/subdomain",when),
        fact("cloudflare",worker,"worker_public_enabled",sub["enabled"],base+"/subdomain",when),
        fact("cloudflare",worker,"worker_privileged_bindings",
             any(x["type"] in PRIVILEGED_BINDINGS for x in bindings),url,when),
    ]

def vercel_facts(project,token,team=None,reader=fetch_json,when=None):
    """Collect three bounded evidence facts from Vercel; never request env vars.

    A negative protection finding is only possible if all three reported
    project-level protection enabled flags are explicitly false AND a recent
    preview-target deployment exists. Unknown states are not treated as off.
    """
    if not isinstance(project,str) or not VERCEL_PROJECT_RE.fullmatch(project):
        raise ValueError("invalid Vercel project name or ID")
    if team is not None and (not isinstance(team,str) or not VERCEL_TEAM_RE.fullmatch(team)):
        raise ValueError("invalid Vercel team ID")
    when=when or utcnow()
    scope="?teamId="+quote(team,safe="") if team else ""
    suffix=("&teamId="+quote(team,safe="")) if team else ""
    base="https://api.vercel.com"
    project_url=base+"/v9/projects/"+quote(project,safe="")
    metadata=reader(project_url+scope,token,"vercel")
    if not isinstance(metadata,dict):
        raise ProviderError("Vercel project metadata was unavailable")
    verified_id=metadata.get("id")
    if not isinstance(verified_id,str) or not re.fullmatch(r"prj_[A-Za-z0-9]{4,100}",verified_id):
        raise ProviderError("Vercel project identifier was invalid")
    project_name=metadata.get("name")
    if not isinstance(project_name,str) or not VERCEL_PROJECT_RE.fullmatch(project_name):
        raise ProviderError("Vercel project name was invalid")
    checks=[metadata.get(k) for k in ("ssoProtection","passwordProtection","trustedIps")]
    protection_flags=[p.get("enabled") if isinstance(p,dict) else None for p in checks]
    if any(value is True for value in protection_flags):
        protected=True
    elif all(value is False for value in protection_flags):
        protected=False
    else:
        protected="unknown"
    preview_url=base+"/v6/deployments?projectId="+quote(verified_id,safe="")+"&target=preview&limit=20"+suffix
    prod_url=base+"/v6/deployments?projectId="+quote(verified_id,safe="")+"&target=production&limit=1"+suffix
    preview=reader(preview_url,token,"vercel")
    production=reader(prod_url,token,"vercel")
    if not isinstance(preview,dict) or not isinstance(preview.get("deployments"),list) or not isinstance(production,dict) or not isinstance(production.get("deployments"),list):
        raise ProviderError("Vercel deployments response was invalid")
    if len(preview["deployments"])>20 or len(production["deployments"])>1:
        raise ProviderError("Vercel returned more deployment records than requested")
    preview_present=True if any(isinstance(item,dict) and item.get("target")=="preview" for item in preview["deployments"]) else "unknown"
    latest=production["deployments"][0] if production["deployments"] else None
    if latest is not None and (not isinstance(latest,dict) or latest.get("target") not in (None,"production")):
        raise ProviderError("Vercel production deployment metadata was unexpected")
    deploy_state=latest.get("readyState",latest.get("state")) if latest else None
    production_error=True if deploy_state=="ERROR" else False if deploy_state=="READY" else "unknown"
    # Restrict snapshots to synthetic boolean / unknown facts and source API
    # URIs without query parameters, token material, source files, or logs.
    return [
        fact("vercel",project_name,"vercel_deployment_protection_configured",protected,project_url,when),
        fact("vercel",project_name,"vercel_recent_preview_observed",preview_present,base+"/v6/deployments",when),
        fact("vercel",project_name,"vercel_latest_production_errored",production_error,base+"/v6/deployments",when),
    ]


def build_snapshot(github_repos=(),cloudflare_workers=(),github_token=None,cloudflare_token=None,
                   account_id=None, reader=fetch_json,when=None,github_workflows=(),
                   vercel_projects=(),vercel_token=None,vercel_team=None):
    when=when or utcnow()
    if not github_repos and not github_workflows and not cloudflare_workers and not vercel_projects:
        raise ValueError("select at least one authorized resource")
    if (github_repos or github_workflows) and not github_token:
        raise ProviderError("GITHUB_TOKEN must be set for GitHub read access")
    if cloudflare_workers and (not cloudflare_token or not account_id):
        raise ProviderError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required")
    if vercel_projects and not vercel_token:
        raise ProviderError("VERCEL_TOKEN required for local Vercel read access")
    if len(github_repos)+len(github_workflows)>20 or len(cloudflare_workers)>50 or len(vercel_projects)>20:
        raise ValueError("collector resource bounds exceeded")
    facts=[]
    selected=[(repo,".github/workflows/deploy-production.yml") for repo in github_repos]
    for entry in github_workflows:
        if not isinstance(entry,str) or ":" not in entry:
            raise ValueError("use --github-workflow owner/repo:.github/workflows/name.yml")
        name,workflow=entry.split(":",1)
        selected.append((name,workflow))
    # Repeated selections are rejected instead of silently double-counted.
    seen_repos=set()
    for repo,workflow in selected:
        if repo in seen_repos:
            raise ValueError("pilot accepts only one selected workflow per repository")
        seen_repos.add(repo)
        facts.extend(github_facts(repo,workflow,github_token,reader,when))
    for worker in dict.fromkeys(cloudflare_workers):
        facts.extend(cloudflare_facts(account_id,worker,cloudflare_token,reader,when))
    if len(set(vercel_projects))!=len(vercel_projects):
        raise ValueError("duplicate Vercel project selection")
    for project in vercel_projects:
        facts.extend(vercel_facts(project,vercel_token,vercel_team,reader,when))
    facts.sort(key=lambda f:(f["provider"],f["asset"],f["signal"]))
    return {"schema":SCHEMA,"captured_at":when,"facts":facts}

def write_private(path,report):
    # Refuse overwrite and create with owner-only permissions from the outset.
    destination=Path(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as file:
        json.dump(report,file,sort_keys=True,indent=2)
        file.write("\n")
    return hashlib.sha256(safe_json(report)).hexdigest()

def main(argv=None):
    parser=argparse.ArgumentParser(description="Read-only QIRA Proof local collector; no uploads")
    parser.add_argument("--github-repo",action="append",default=[],help="Explicit repository owner/name")
    parser.add_argument("--vercel-project",action="append",default=[],help="Explicit Vercel project ID or name")
    parser.add_argument("--cloudflare-worker",action="append",default=[],help="Explicit Worker name")
    parser.add_argument("--github-workflow",action="append",default=[],
      help="Select workflow explicitly as owner/repo:.github/workflows/name.yml")
    parser.add_argument("--out",required=True,help="Private output JSON file; existing files never overwritten")
    args=parser.parse_args(argv)
    try:
        report=build_snapshot(args.github_repo,args.cloudflare_worker,
          os.environ.get("GITHUB_TOKEN"),os.environ.get("CLOUDFLARE_API_TOKEN"),
          os.environ.get("CLOUDFLARE_ACCOUNT_ID"),github_workflows=args.github_workflow,
          vercel_projects=args.vercel_project,vercel_token=os.environ.get("VERCEL_TOKEN"),
          vercel_team=os.environ.get("VERCEL_TEAM_ID"))
        digest=write_private(args.out,report)
    except (ValueError,ProviderError,FileExistsError) as e:
        parser.error(str(e))
    print(json.dumps({"saved":str(Path(args.out)),"facts":len(report["facts"]),
                      "snapshot_sha256":digest,"uploaded":False},sort_keys=True))

if __name__=="__main__":
    main()
