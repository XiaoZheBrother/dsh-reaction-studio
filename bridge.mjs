import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, join, delimiter, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'
const require = createRequire(import.meta.url)

export const actions = new Set(['catalog','start','status','observation','pause_analysis','replay'])
export function invoke(config, action, args = {}) {
  if (!actions.has(action)) throw Error('Unsupported reaction tool')
  if (!config.python || !isAbsolute(config.configPath)) throw Error('请配置 python 与 configPath 绝对路径')
  const live = join(dirname(require.resolve('dsh-live-studio/package.json')), 'backend')
  return new Promise((resolve, reject) => {
    const child = spawn(config.python, ['-u', fileURLToPath(new URL('./backend/plugin_rpc.py', import.meta.url)), '--config', config.configPath], {
      windowsHide: true, shell: false,
      env: {...process.env, PYTHONUTF8:'1', PYTHONPATH:[live, process.env.PYTHONPATH].filter(Boolean).join(delimiter)},
      stdio:['pipe','pipe','pipe']
    })
    let out='', oversized=false
    const timer=setTimeout(()=>{child.kill();reject(Error('工具回执超时；重试前先查询原 job_id 的状态'))},60000)
    child.stdout.on('data',data=>{out+=data;if(out.length>4_000_000){oversized=true;child.kill()}})
    child.stderr.on('data',()=>{})
    child.on('error',error=>{clearTimeout(timer);reject(error)})
    child.on('close',code=>{clearTimeout(timer);if(code || oversized)return reject(Error('工具执行失败，请检查配置；后台任务状态请用原 job_id 查询'));
      try{const value=JSON.parse(out);if(value.error)reject(Error(value.error));else resolve(value)}catch{reject(Error('工具返回了无效结果'))}})
    child.stdin.on('error',()=>{})
    child.stdin.end(JSON.stringify({action,args}))
  })
}
