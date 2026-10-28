// Browser-local conversations; inference receives the selected conversation only.
// Escape source text before adding a deliberately small, safe Markdown subset.
function formatInline(text) {
 return text.split(/(`[^`\n]+`)/g).map(part=>part.startsWith('`')
  ? '<code>'+esc(part.slice(1,-1))+'</code>'
  : esc(part).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')).join('');
}
function formatAssistant(text) {
 return text.split(/(```[\s\S]*?(?:```|$))/g).map(part=>{
  if(part.startsWith('```'))return '<pre><code>'+esc(part.replace(/^```[^\n]*\n?/,'').replace(/```$/,''))+'</code></pre>';
  const blocks=[];let paragraph=[],items=[],kind=null;
  const flushParagraph=()=>{if(paragraph.length){blocks.push('<p>'+formatInline(paragraph.join('\n'))+'</p>');paragraph=[]}};
  const flushList=()=>{if(items.length){blocks.push('<'+kind+'>'+items.map(t=>'<li>'+formatInline(t)+'</li>').join('')+'</'+kind+'>');items=[];kind=null}};
  for(const line of part.split('\n')) {
   const heading=line.match(/^#{1,6}\s+(.+)$/),item=line.match(/^\s*(?:([-*])|\d+\.)\s+(.+)$/);
   if(heading){flushParagraph();flushList();blocks.push('<h3>'+formatInline(heading[1])+'</h3>')}
   else if(item){flushParagraph();const next=item[1]?'ul':'ol';if(kind&&kind!==next)flushList();kind=next;items.push(item[2])}
   else if(!line.trim()){flushParagraph();flushList()}
   else{flushList();paragraph.push(line)}
  }
  flushParagraph();flushList();return blocks.join('');
 }).join('');
}
let conversations=[];
try{const saved=JSON.parse(localStorage.getItem('tokenflow.conversations.v1')||'[]');if(Array.isArray(saved))conversations=saved.filter(c=>c&&typeof c.id==='string'&&Array.isArray(c.messages)).slice(0,20)}catch{}
let conversationId=conversations[0]?.id||null;
function currentConversation(){return conversations.find(c=>c.id===conversationId)}
function persistConversations(){try{localStorage.setItem('tokenflow.conversations.v1',JSON.stringify(conversations.slice(0,20)))}catch{toast('Browser storage is full. This chat remains available until you close the page.')}}
function renderConversations(){$('conversation-list').innerHTML=conversations.filter(c=>c.messages.length).map(c=>`<button class="conversation-item ${c.id===conversationId?'selected':''}" data-conversation="${esc(c.id)}">${esc(c.title)}</button>`).join('')||'<div class="conversation-empty">Your conversations appear here.</div>'}
function renderMessages(scroll=false){
 const c=currentConversation();const empty=!c?.messages.length;$('chat').classList.toggle('is-empty',empty);$('starter-prompts').classList.toggle('hidden',!empty);
 if(empty){$('messages').innerHTML=`<div class="chat-empty"><h1>New conversation</h1><p>Draft a message, work through a question, or write some code.</p></div>`;return}
 $('messages').innerHTML=c.messages.map((m,i)=>`<article class="message ${m.role}"><div class="message-label">${m.role==='user'?'You':'TokenFlow'}</div><div class="message-content" id="message-${i}">${(m.role==='assistant'?formatAssistant(m.content):esc(m.content))||(streaming&&i===c.messages.length-1?'<span class="typing-dot">Generating</span>':'')}</div>${m.role==='assistant'&&m.meta?`<div class="message-meta"><span>${esc(m.meta)}${m.model?' · '+esc(m.model.split('/').pop()):''}</span><button class="copy-answer" data-copy="${i}" aria-label="Copy response">Copy</button></div>`:''}${m.outcome==='failed'?`<button class="message-retry" data-retry="${i}">Retry request</button>`:''}</article>`).join('');
 if(scroll)$('chat-scroll').scrollTop=$('chat-scroll').scrollHeight;
}
function newConversation(){if(streaming)return;conversationId=null;$('page-name').textContent='New chat';$('chat-input').value='';$('chat-input').style.height='auto';renderMessages();renderConversations();switchView('chat');$('chat-input').focus()}
$('new-chat').addEventListener('click',newConversation);
$('conversation-list').addEventListener('click',e=>{const button=e.target.closest('[data-conversation]');if(!button)return;if(streaming){toast('Wait for this answer or stop generation first.');return}conversationId=button.dataset.conversation;renderMessages(true);renderConversations();switchView('chat')});
$('chat').addEventListener('click',e=>{const button=e.target.closest('[data-prompt]');if(button){$('chat-input').value=button.dataset.prompt;$('chat-input').focus()}});
$('chat-input').addEventListener('input',()=>{const input=$('chat-input');input.style.height='auto';input.style.height=Math.min(160,input.scrollHeight)+'px'});
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$('chat-send').disabled)$('chat-form').requestSubmit()}});
$('chat-form').addEventListener('submit',async e=>{e.preventDefault();const prompt=$('chat-input').value.trim();if(!prompt||streaming)return;if(state?.run?.status==='running'){toast('Please wait for the request group to finish.');return}let c=currentConversation();if(!c){c={id:crypto.randomUUID(),title:prompt.slice(0,32),messages:[]};conversations.unshift(c);conversations=conversations.slice(0,20);conversationId=c.id}c.messages.push({role:'user',content:prompt});const context=c.messages.filter(m=>m.content&&(!m.outcome||m.outcome==='completed')).slice(-20).map(({role,content})=>({role,content}));const answer={role:'assistant',content:'',outcome:'pending'};c.messages.push(answer);streaming=true;currentRequest='chat-'+crypto.randomUUID().replaceAll('-','').slice(0,16);$('chat-input').value='';$('chat-input').style.height='auto';$('chat-send').classList.add('hidden');$('chat-stop').classList.remove('hidden');$('new-chat').disabled=true;$('page-name').textContent=c.title;renderMessages(true);renderConversations();let started=performance.now(),first=null,tokens=0;
try{const response=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:currentRequest,prompt,messages:context,max_tokens:Number($('chat-limit').value)})});if(!response.ok){const error=await response.json();throw new Error(({request_rate_limit:'Too many requests. Try again shortly.',client_concurrency_limit:'This client has too many active requests. Wait for one to finish.',client_token_budget:'This client has reached its estimated token budget.'})[error.code]||error.error)}const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let boundary;while((boundary=buffer.indexOf('\n\n'))!==-1){const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const line=block.split('\n').find(l=>l.startsWith('data: '));if(!line)continue;const ev=JSON.parse(line.slice(6));if(ev.event==='assigned')answer.model=ev.model;if(ev.event==='token'){if(first===null)first=performance.now()-started;tokens++;answer.content=ev.text!=null?ev.text:answer.content+ev.delta;const nearBottom=$('chat-scroll').scrollHeight-$('chat-scroll').scrollTop-$('chat-scroll').clientHeight<100;renderMessages(nearBottom)}if(['completed','failed','cancelled'].includes(ev.event)){answer.outcome=ev.event;answer.meta=ev.event==='completed'?`${((performance.now()-started)/1000).toFixed(1)}s · ${tokens} tokens${ev.reason==='length'?' · output limit reached':''}`:ev.event==='cancelled'?'Generation stopped':'Generation failed. You can try again.';if(ev.event==='failed')throw new Error(ev.reason||'Generation failed')}}}if(answer.outcome==='pending')throw new Error('Connection interrupted. Please try again.')}catch(error){answer.outcome='failed';answer.meta='Connection interrupted. Retry when the service is ready.';answer.content||='Could not complete the answer.';toast(error.message)}finally{streaming=false;currentRequest=null;persistConversations();renderMessages(true);renderConversations();$('chat-send').classList.remove('hidden');$('chat-stop').classList.add('hidden');$('new-chat').disabled=false;await poll();$('chat-input').focus()}});
$('chat-stop').addEventListener('click',async()=>{try{if(currentRequest)await api('/api/cancel',{request_id:currentRequest})}catch(e){toast(e.message)}});
renderMessages();renderConversations();switchView('chat');
$('messages').addEventListener('click',e=>{const button=e.target.closest('[data-retry]');if(!button||streaming)return;const c=currentConversation(),index=Number(button.dataset.retry);const question=c?.messages[index-1];if(question?.role!=='user')return;const prompt=question.content;if(index===c.messages.length-1){c.messages.splice(index-1,2);persistConversations();renderMessages()}$('chat-input').value=prompt;$('chat-form').requestSubmit()});

$('messages').addEventListener('click',async e=>{const button=e.target.closest('[data-copy]');if(!button)return;const message=currentConversation()?.messages[Number(button.dataset.copy)];if(!message?.content)return;try{await navigator.clipboard.writeText(message.content);toast('Response copied')}catch{toast('Could not copy. Select the response text to copy it.')}});
