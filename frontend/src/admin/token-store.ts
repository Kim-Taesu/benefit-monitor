// Token storage. GitHub Pages serves every kim-taesu.github.io project from one origin, so
// localStorage is readable by the other pages: the default is this tab's sessionStorage, and
// localStorage is used only when the user opts in. Every access is guarded (storage may be blocked).
export const TOKEN_KEY='benefit-monitor.admin-token';
type Store=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
type Get=()=>Store;
const session:Get=()=>sessionStorage,local:Get=()=>localStorage;

function guard<T>(fn:()=>T,fallback:T):T{try{return fn();}catch{return fallback;}}

export function loadToken(s:Get=session,l:Get=local):string{
 return guard(()=>s().getItem(TOKEN_KEY),null)||guard(()=>l().getItem(TOKEN_KEY),null)||'';
}
export function clearToken(s:Get=session,l:Get=local):void{
 guard(()=>s().removeItem(TOKEN_KEY),undefined);guard(()=>l().removeItem(TOKEN_KEY),undefined);
}
export function saveToken(value:string,remember:boolean,s:Get=session,l:Get=local):void{
 clearToken(s,l);
 guard(()=>(remember?l:s)().setItem(TOKEN_KEY,value),undefined);
}
