#!/usr/bin/env python3
"""QIRA Proof read-only collector for GitHub and Cloudflare configuration metadata.

Never sends provider tokens or raw content to QIRA services. Uses GET only.
The resulting local snapshot may disclose infrastructure names; store privately.

Requires: GITHUB_TOKEN for --github-repo,
          CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID for --cloudflare-worker.
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
        raise ProviderError("GitHub API returned unexpected content")
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
    snapshot=reader(base+"/contents/"+encoded,token,"github")
    if snapshot.get("encoding")!="base64" or not isinstance(snapshot.get("content"),str):
        raise ProviderError("workflow not available as bounded base64 content")
    text=base64.b64decode(snapshot["content"],validate=False)
    if len(text)>128_000:
        raise ProviderError("workflow file exceeds 128 KB")
    text=text.decode("utf-8")
    active_lines=[x for x in text.splitlines() if not x.lstrip().startswith("#")]
    has_scan=any(re.search(r"(?<![A-Za-z0-9_-])ssh-keyscan(?:[ \t]|$)",line) for line in active_lines)
    source=f"https://github.com/{repo}/blob/main/{workflow}"
    facts=[fact("github",repo,"runtime_ssh_keyscan",has_scan,source,when)]
    if has_scan:
        # Proving SSH host-key pinning requires authoritative key material and
        # a trusted out-of-band comparison, NOT a string search.
        facts.append(fact("github",repo,"ssh_host_key_pinned","unknown",source,when))
    try:
        reader(base+"/branches/main/protection",token,"github")
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

def build_snapshot(github_repos=(),cloudflare_workers=(),github_token=None,cloudflare_token=None,
                   account_id=None, reader=fetch_json,when=None):
    when=when or utcnow()
    if not github_repos and not cloudflare_workers:
        raise ValueError("select at least one authorized resource")
    if github_repos and not github_token:
        raise ProviderError("GITHUB_TOKEN must be set for GitHub read access")
    if cloudflare_workers and (not cloudflare_token or not account_id):
        raise ProviderError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required")
    if len(github_repos)>20 or len(cloudflare_workers)>50:
        raise ValueError("collector resource bounds exceeded")
    facts=[]
    for repo in dict.fromkeys(github_repos):
        facts.extend(github_facts(repo,".github/workflows/deploy-production.yml",github_token,reader,when))
    for worker in dict.fromkeys(cloudflare_workers):
        facts.extend(cloudflare_facts(account_id,worker,cloudflare_token,reader,when))
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
    parser.add_argument("--cloudflare-worker",action="append",default=[],help="Explicit Worker name")
    parser.add_argument("--out",required=True,help="Private output JSON file; existing files never overwritten")
    args=parser.parse_args(argv)
    try:
        report=build_snapshot(args.github_repo,args.cloudflare_worker,
          os.environ.get("GITHUB_TOKEN"),os.environ.get("CLOUDFLARE_API_TOKEN"),
          os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
        digest=write_private(args.out,report)
    except (ValueError,ProviderError,FileExistsError) as e:
        parser.error(str(e))
    print(json.dumps({"saved":str(Path(args.out)),"facts":len(report["facts"]),
                      "snapshot_sha256":digest,"uploaded":False},sort_keys=True))

if __name__=="__main__":
    main()
