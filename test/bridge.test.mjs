import test from 'node:test'
import assert from 'node:assert/strict'
import {actions,invoke} from '../bridge.mjs'
test('bridge only dispatches six bounded operations, never shell commands',()=>{
  assert.equal(actions.size,6)
  assert.throws(()=>invoke({},'exec',{command:'anything'}),/Unsupported/)
  assert.throws(()=>invoke({python:'python',configPath:'relative'},'catalog'),/绝对路径/)
})
