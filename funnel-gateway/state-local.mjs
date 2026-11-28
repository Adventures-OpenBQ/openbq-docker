// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
// SQLite supplies cross-process locking, atomic body+fence records and crash recovery.
import {DatabaseSync} from 'node:sqlite';
import {constants,lstatSync,existsSync,mkdirSync,openSync,closeSync,readFileSync,readdirSync,chmodSync,unlinkSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {createHash} from 'node:crypto';
import {stateFile} from './policy.mjs';
const DB='.state.sqlite', MAX_BYTES=2*1024*1024, MAX_FILES=200;
const MAX_RECORDS=2000, MAX_WRITERS=256;
function regular(path){const st=lstatSync(path);if(!st.isFile()||st.isSymbolicLink())throw Error('Unsafe state file');}
function directory(path){const st=lstatSync(path);if(!st.isDirectory()||st.isSymbolicLink())throw Error('Unsafe state directory');}
function sweepLegacyTemps(dir){
  for(const name of readdirSync(dir)){
    if(!name.startsWith('.tmp-'))continue;
    const path=join(dir,name);
    try{const st=lstatSync(path);if(!st.isDirectory()&&Date.now()-st.mtimeMs>60000)unlinkSync(path);}catch{/* Raced a legacy writer or cleanup. */}
  }
}
function legacy(dir){
  const files={};
  if(!existsSync(dir))return files;
  directory(dirname(dir));directory(dir);
  sweepLegacyTemps(dir);
  for(const stored of readdirSync(dir)){
    let name;try{name=decodeURIComponent(stored);}catch{continue;}
    if(!stateFile(name))continue;
    const path=join(dir,stored);regular(path);
    const fd=openSync(path,constants.O_RDONLY|constants.O_NOFOLLOW);
    try{files[name]=readFileSync(fd,'utf8');}finally{closeSync(fd);}
  }
  return files;
}
function connect(dir){
  directory(dirname(dir));directory(dir);
  const path=join(dir,DB);
  for(const suffix of ['', '-journal','-wal','-shm'])if(existsSync(path+suffix))regular(path+suffix);
  try{closeSync(openSync(path,'wx',0o600));}catch(e){if(e.code!=='EEXIST')throw e;}
  regular(path);chmodSync(path,0o600);
  const db=new DatabaseSync(path);db.exec('PRAGMA busy_timeout=5000; PRAGMA synchronous=FULL;');
  return db;
}
function setup(db){
  db.exec('CREATE TABLE IF NOT EXISTS records(name TEXT PRIMARY KEY, body TEXT, fences TEXT NOT NULL); CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);');
}
export function stateVersion(req){
  const writer=req.headers['x-bdobb-state-writer'], raw=req.headers['x-bdobb-state-sequence'];
  const count=name=>req.rawHeaders.filter((v,i)=>i%2===0&&v.toLowerCase()===name).length;
  if(writer===undefined&&raw===undefined)return null;
  if(count('x-bdobb-state-writer')!==1||count('x-bdobb-state-sequence')!==1||
      typeof writer!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(writer)||
      typeof raw!=='string'||! /^[1-9][0-9]{0,15}$/.test(raw)||!Number.isSafeInteger(Number(raw)))return false;
  return {writer,sequence:Number(raw),raw};
}
function importLegacy(db,dir){
  setup(db);
  if(!db.prepare("SELECT value FROM metadata WHERE key='imported'").get()){
    const insert=db.prepare('INSERT OR IGNORE INTO records VALUES(?,?,?)');
    for(const [file,text] of Object.entries(legacy(dir)))insert.run(file,text,'{}');
    db.prepare("INSERT INTO metadata VALUES('imported','1')").run();
  }
}
export function readState(dir){
  if(!existsSync(join(dir,DB)))return legacy(dir);
  directory(dirname(dir));directory(dir);sweepLegacyTemps(dir);
  const db=connect(dir);
  try{
    db.exec('BEGIN IMMEDIATE');importLegacy(db,dir);
    const files=Object.fromEntries(db.prepare('SELECT name,body FROM records WHERE body IS NOT NULL').all().map(r=>[r.name,r.body]));
    db.exec('COMMIT');return files;
  }catch(error){try{db.exec('ROLLBACK');}catch{}throw error;}
  finally{db.close();}
}
export function commitState(dir,name,body,version){
  if(!stateFile(name))throw Error('Unsafe state name');
  mkdirSync(dirname(dir),{recursive:true,mode:0o700});directory(dirname(dir));
  mkdirSync(dir,{recursive:true,mode:0o700});directory(dir);
  const db=connect(dir);
  try{
    db.exec('BEGIN IMMEDIATE');importLegacy(db,dir);
    const old=db.prepare('SELECT body,fences FROM records WHERE name=?').get(name);
    const fences=old?JSON.parse(old.fences):{};
    const fingerprint=createHash('sha256').update(body===null?'DELETE':'PUT\0'+body).digest('hex');
    const finish=status=>{db.exec('COMMIT');return status;};
    if(version){
      const prior=fences[version.writer];
      if(prior&&version.sequence<=prior.sequence)return finish(version.sequence===prior.sequence&&fingerprint===prior.fingerprint?204:409);
      if(!prior&&Object.keys(fences).length>=MAX_WRITERS)return finish(413);
      fences[version.writer]={sequence:version.sequence,fingerprint};
    }else if(Object.keys(fences).length)return finish(409);
    const quota=db.prepare('SELECT count(*) AS files,coalesce(sum(length(CAST(body AS BLOB))),0) AS bytes FROM records WHERE body IS NOT NULL AND name<>?').get(name);
    if(body!==null&&(quota.files>=MAX_FILES||quota.bytes+Buffer.byteLength(body)>MAX_BYTES))return finish(413);
    if(!old&&db.prepare('SELECT count(*) AS n FROM records').get().n>=MAX_RECORDS)return finish(413);
    if(body===null&&!version)db.prepare('DELETE FROM records WHERE name=?').run(name);
    else db.prepare('INSERT INTO records VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET body=excluded.body,fences=excluded.fences').run(name,body,JSON.stringify(fences));
    return finish(204);
  }catch(error){try{db.exec('ROLLBACK');}catch{}throw error;}
  finally{db.close();}
}
