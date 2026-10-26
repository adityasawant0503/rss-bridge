// Theme: follows the phone/computer setting; the sun/moon button (#thm) overrides it and the choice is shared by all PulsEdge pages.
(function(){
  var d=document.documentElement,b=document.getElementById("thm"),mq=matchMedia("(prefers-color-scheme: dark)");
  if(!b)return;
  function sys(){return mq.matches?"dark":"light"}
  function cur(){return d.getAttribute("data-theme")||sys()}
  function save(v){try{v?localStorage.setItem("th",v):localStorage.removeItem("th")}catch(e){}}
  function sync(){var k=cur()==="dark",l=k?"Switch to light mode":"Switch to dark mode";
    b.querySelector(".i-sun").toggleAttribute("hidden",!k);b.querySelector(".i-moon").toggleAttribute("hidden",k);b.setAttribute("aria-label",l);b.title=l}
  b.addEventListener("click",function(){var n=cur()==="dark"?"light":"dark";if(n===sys()){d.removeAttribute("data-theme");save(null)}else{d.setAttribute("data-theme",n);save(n)}sync()});
  function onSys(){if(d.getAttribute("data-theme")===sys()){d.removeAttribute("data-theme");save(null)}sync()}
  if(mq.addEventListener)mq.addEventListener("change",onSys);else mq.addListener(onSys);
  window.addEventListener("storage",function(e){if(e.key!=="th")return;if(e.newValue)d.setAttribute("data-theme",e.newValue);else d.removeAttribute("data-theme");sync()});
  sync();
})();
