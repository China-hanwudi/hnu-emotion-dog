// Project adapter based on the VSS document. Validate against the organizer's script.
const CryptoJS = require('crypto-js');
const enc = x => encodeURIComponent(String(x)).replace(/[!'()*]/g, x => '%' + x.charCodeAt(0).toString(16).toUpperCase());
const value = name => { const v = pm.environment.get(name); if (!v) throw new Error('Missing environment variable: ' + name); return String(v); };
const params = {tenantCode:value('tenant_code'),accessKey:value('access_key'),deviceId:value('device_id'),nonce:CryptoJS.lib.WordArray.random(8).toString(),timestamp:String(Date.now())};
pm.request.url.query.each(q => {if (!q.disabled) params[q.key] = pm.variables.replaceIn(q.value);});
if (pm.request.method.toUpperCase() === 'POST' && pm.request.body && pm.request.body.mode === 'raw') {
  params.content = pm.variables.replaceIn(pm.request.body.raw || '');
}
const sorted = Object.keys(params).sort().map(k=>enc(k)+'='+enc(params[k])).join('&');
const stringToSign = pm.request.method.toUpperCase() + '&%2F&' + enc(sorted);
const secret = value('access_secret') + '&';
const digest = pm.environment.get('hmac_algorithm') === 'sha256' ? CryptoJS.HmacSHA256(stringToSign,secret) : CryptoJS.HmacSHA1(stringToSign,secret);
const headers = {'VSS-Tenant-Code':params.tenantCode,'VSS-Access-Key':params.accessKey,'VSS-Device-Id':params.deviceId,'VSS-Nonce':params.nonce,'VSS-Timestamp':params.timestamp,'VSS-Sign':CryptoJS.enc.Base64.stringify(digest)};
Object.entries(headers).forEach(([key,value])=>pm.request.headers.upsert({key,value}));

