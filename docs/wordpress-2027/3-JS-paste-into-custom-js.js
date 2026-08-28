(function(){
  "use strict";
  var tries=0;
  function init(){
    var root=document.getElementById("fl27");
    if(!root||!document.getElementById("fl-q")){
      if(++tries<60){return setTimeout(init,100);}   // wait up to 6s for the content
      return;
    }
    if(root.getAttribute("data-fl-init")==="1") return;  // don't bind twice
    root.setAttribute("data-fl-init","1");
    build(root);
  }
  function build(root){

  var q=document.getElementById("fl-q"),k=document.getElementById("fl-k"),
      t=document.getElementById("fl-t"),ch=document.getElementById("fl-c"),ex=document.getElementById("fl-ex"),ct=document.getElementById("fl-ct"),
      ed=document.getElementById("fl-ed"),sv=document.getElementById("fl-sv"),
      cards=root.querySelectorAll("details.p"),EDIT=false;

  function filter(){
    var s=(q.value||"").toLowerCase().trim(),ck=k.value,ctp=t.value,cc=ch?ch.value:"",n=0;
    for(var i=0;i<cards.length;i++){
      var el=cards[i],
          ok=(!s||el.getAttribute("data-s").indexOf(s)>-1)&&
             (!ck||el.getAttribute("data-k")===ck)&&
             (!ctp||el.getAttribute("data-t")===ctp)&&
             (!cc||el.getAttribute("data-ch")===cc);
      el.style.display=ok?"":"none"; if(ok)n++;
    }
    ct.textContent=n+" of "+cards.length+" plans";
  }
  [q,k,t,ch].forEach(function(e){if(e){
    e.addEventListener("input",filter);
    e.addEventListener("change",filter);
    e.addEventListener("keyup",filter);
  }});

  ed.addEventListener("click",function(){
    EDIT=!EDIT;
    ed.textContent="Edit: "+(EDIT?"on":"off");
    ed.className=EDIT?"pri":"";
    var tds=root.querySelectorAll("td.v");
    for(var i=0;i<tds.length;i++){tds[i].contentEditable=EDIT?"true":"false"}
  });

  sv.addEventListener("click",function(){
    var out=[];
    for(var i=0;i<cards.length;i++){
      var el=cards[i],code=el.querySelector(".pc").textContent.split("·")[0].trim(),
          rows=el.querySelectorAll("tbody tr"),o={cms:code,
          name:el.querySelector(".pn").textContent.trim(),fields:{}};
      for(var j=0;j<rows.length;j++){
        var c=rows[j].querySelectorAll("td");
        if(c.length>2)o.fields[c[0].textContent.trim()]={"2026":c[1].textContent.trim(),"2027":c[2].textContent.trim()};
      }
      out.push(o);
    }
    var b=new Blob([JSON.stringify(out,null,1)],{type:"application/json"}),
        u=URL.createObjectURL(b),a=document.createElement("a");
    a.href=u;a.download="first-look-2027-edits.json";
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(function(){URL.revokeObjectURL(u)},900);
  });

  if(ex){ex.addEventListener("click",function(){
    var open=ex.textContent.indexOf("Expand")>-1;
    for(var i=0;i<cards.length;i++){if(cards[i].style.display!=="none")cards[i].open=open}
    ex.textContent=open?"Collapse all":"Expand all";
  })}

  filter();
  }
  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",init);
  }else{ init(); }
  window.addEventListener("load",init);
})();