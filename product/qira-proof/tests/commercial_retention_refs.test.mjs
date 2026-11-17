import test from "node:test";
import assert from "node:assert/strict";
import {purgeOldOrderRows} from "../commercial/payments.mjs";

const TODAY=1794890000;
const OLD=TODAY-181*86400;
class ReferencedLedger{
 constructor(){
  this.events=new Map([["evt_old",OLD],["evt_new",TODAY]]);
  this.orders=new Map([
   ["old_unlinked",{updated_at:OLD}],
   ["old_cancelled",{updated_at:OLD}],
   ["old_active",{updated_at:OLD}],
   ["old_report",{updated_at:OLD}],
   ["old_otp",{updated_at:OLD}],
   ["old_notice",{updated_at:OLD}],
   ["recent",{updated_at:TODAY}]
  ]);
  this.intakes=new Map([
   ["old_cancelled",{submitted_at:OLD,state:"cancelled"}],
   ["old_active",{submitted_at:OLD,state:"in_review"}],
   ["old_report",{submitted_at:OLD,state:"delivered"}]
  ]);
  this.reports=new Set(["old_report"]);
  this.codes=new Set(["old_otp"]);
  this.notices=new Set(["old_notice"]);
  this.statements=[];
  this.fail=false;
 }
 prepare(sql){return {bind:(...params)=>({sql,params})};}
 async batch(statements){
  this.statements=statements.map(s=>s.sql);
  if(this.fail)return statements.map(()=>({success:false}));
  for(const {sql,params} of statements){
   const cutoff=params[0];
   if(sql.startsWith("DELETE FROM qira_events")){
    for(const [id,t] of this.events)if(t<cutoff)this.events.delete(id);
   }else if(sql.startsWith("DELETE FROM qira_intakes")){
    // Assert the exact safeguards rather than masking a dangerous source change.
    if(!sql.includes("state='cancelled'")||!sql.includes("NOT EXISTS (SELECT 1 FROM qira_deliverables"))throw Error("Cancelled-only retention guard missing");
    for(const [sid,i] of this.intakes)if(i.submitted_at<cutoff&&i.state==="cancelled"&&!this.reports.has(sid))this.intakes.delete(sid);
   }else if(sql.startsWith("DELETE FROM qira_orders")){
    for(const required of ["NOT EXISTS (SELECT 1 FROM qira_intakes","NOT EXISTS (SELECT 1 FROM qira_deliverables","NOT EXISTS (SELECT 1 FROM qira_report_challenges","NOT EXISTS (SELECT 1 FROM qira_customer_notices"])assert.ok(sql.includes(required),required);
    for(const [sid,o] of this.orders)
     if(o.updated_at<cutoff&&!this.intakes.has(sid)&&!this.reports.has(sid)&&!this.codes.has(sid)&&!this.notices.has(sid))this.orders.delete(sid);
   }else throw Error("Unexpected cleanup SQL");
  }
  return statements.map(()=>({success:true}));
 }
}
test("180-day cleanup removes only safely unreferenced orders and cancelled intakes",async()=>{
 const db=new ReferencedLedger();
 assert.equal(await purgeOldOrderRows(db,TODAY),true);
 assert.deepEqual([...db.events.keys()],["evt_new"]);
 assert.deepEqual([...db.orders.keys()],["old_active","old_report","old_otp","old_notice","recent"]);
 assert.deepEqual([...db.intakes.keys()],["old_active","old_report"]);
 assert.equal(db.statements.length,3);
});
test("cleanup refuses an absent database, an invalid clock and failed writes",async()=>{
 await assert.rejects(purgeOldOrderRows(null,TODAY),/retention_unavailable/);
 await assert.rejects(purgeOldOrderRows(new ReferencedLedger(),0),/retention_unavailable/);
 const db=new ReferencedLedger();db.fail=true;
 await assert.rejects(purgeOldOrderRows(db,TODAY),/retention_write_failed/);
});
