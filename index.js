import z from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { invoke } from './bridge.mjs'
export const name='dsh-reaction-studio'
export const inject=['tools']
export const Config=z.object({enabled:z.boolean().default(false),python:z.string().default('python'),configPath:z.string().default('')})
const output={schema:{type:'json'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]}
export function apply(ctx,config){
  if(!config.enabled)return
  const job={job_id:{type:'string',required:true,description:'Existing job ID; reuse it when checking or resuming.'}}
  const add=(action,description,parameters)=>ctx.tools.register(defineTool({name:'reaction_'+action,description,parameters,output,isConcurrencySafe:()=>false,execute:args=>invoke(config,action,args)}))
  add('catalog','查询授权素材和已有任务；不启动制作。',{})
  add('start','启动或恢复离线陪看。先查 catalog，只接受已配置素材 ID；自主观察、决定说话或暂停，并制作正常速度视频。相同 job_id 不重复启动。不公开发布。回执不等于完成，请查询 status。',{material_id:{type:'string',required:true},...job,seconds:{type:'number',description:'0 为完整授权片段'},afterword:{type:'boolean'}})
  add('status','查询进度、暂停回看回执和成片路径。',job)
  add('observation','读取已经看过的观察与近期发言；可能误判，不透露后续。',job)
  add('pause_analysis','自行决定值得展开时请求暂停分析；排队后在安全边界执行，讲完自动继续。不是每次都需要暂停。',{...job,topic:{type:'string',required:true}})
  add('replay','请求回看最近 1 至 10 秒已经看到的内容；不提前看后续。',{...job,seconds:{type:'number'}})
}
