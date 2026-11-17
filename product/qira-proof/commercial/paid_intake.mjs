// Only included on a webhook-confirmed paid Checkout Session with a buyer
// email digest available. Uses same-origin intake; no GitHub tokens or files.
export const PAID_INTAKE_SCRIPT = String.raw`<script>
(function(){
 const form=document.getElementById("intakeComposer"),status=document.getElementById("composerOutput");
 const email=document.getElementById("intakeEmail"),repo=document.getElementById("intakeRepo"),receipt=document.getElementById("intakeReceipt");
 if(!form||!status||!email||!repo||!receipt)return;
 try{
  const selected=sessionStorage.getItem("qira_proof_repo");
  if(selected&&!repo.value&&/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9_.-]{1,100}$/.test(selected))repo.value=selected;
 }catch{}
 let submitting=false;
 form.addEventListener("submit",async function(event){
  event.preventDefault();
  if(submitting)return;
  const checkoutEmail=email.value.trim(),repository=repo.value.trim(),sessionId=receipt.value.trim();
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(checkoutEmail)||checkoutEmail.length>254){
   status.textContent="Enter the email used for Stripe checkout.";email.focus();return;
  }
  if(!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9_.-]{1,100}$/.test(repository)||repository.includes("..")){
   status.textContent="Enter only the GitHub owner/repository name, without a URL, token or extra path.";repo.focus();return;
  }
  if(!/^cs_live_[A-Za-z0-9]{10,255}$/.test(sessionId)){
   status.textContent="The checkout reference is missing. Return from Stripe or contact Qira.";return;
  }
  submitting=true;
  const submit=form.querySelector('button[type="submit"]');
  if(submit)submit.disabled=true;
  status.textContent="Submitting your review request securely…";
  try{
   const response=await fetch("/api/orders/intake",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({session_id:sessionId,email:checkoutEmail,repository})});
   const result=await response.json();
   if(response.ok&&result.received){
    form.hidden=true;
    status.textContent="Review request received. Qira will contact you using your checkout email to confirm the repository authorization and delivery timeline. No further payment is needed.";
   }else if(response.status===403){
    status.textContent="We could not match this paid order to that checkout email. Use the email on your Stripe receipt, or contact Qira support.";
   }else{
    status.textContent="The request could not be saved right now. No new payment is needed. Try again or contact Qira support.";
   }
  }catch{
   status.textContent="The connection failed. No new payment is needed. Try again or contact Qira support.";
  }finally{if(submit)submit.disabled=false;submitting=false;}
 });
})();
</script>`;
