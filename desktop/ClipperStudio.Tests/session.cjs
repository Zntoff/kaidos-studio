// All test sessions use the same bootstrap as the product. No authentication bypass exists.
module.exports=async function securePage(page,base){
 const response=await page.request.get(base+'/');
 const token=(await response.text()).match(/name="kairos-csrf" content="([a-fA-F0-9]+)"/)?.[1];
 if(!token)throw Error('Session bootstrap failed');
 for(const method of ['post','put','delete','patch']){
  const original=page.request[method].bind(page.request);
  page.request[method]=(url,options={})=>original(url,{...options,headers:{...options.headers,'X-Kairos-CSRF':token}});
 }
};
