#!/usr/bin/env node
// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import {execFileSync} from "node:child_process";
import {createHash} from "node:crypto";
import {readFileSync,mkdirSync,writeFileSync} from "node:fs";
import {resolve} from "node:path";
const [checkout, destination]=process.argv.slice(2);
if(!checkout || !destination)throw new Error("usage: node table-service/prepare-source.mjs <bdobb checkout> <NEW context directory>");
const lock=JSON.parse(readFileSync(new URL("./source.lock.json",import.meta.url),"utf8"));
if(!/^[a-f0-9]{40}$/.test(lock.revision) || !/^[a-f0-9]{40}$/.test(lock.tree))throw new Error("Invalid source lock");
const git=(...args)=>execFileSync("git",["-C",resolve(checkout),...args],{maxBuffer:128*1024*1024});
if(git("rev-parse",`${lock.revision}^{tree}`).toString().trim()!==lock.tree)throw new Error("Pinned source tree mismatch");
const dockerfile=git("show",`${lock.revision}:deploy/table-service/Dockerfile`);
const sha=bytes=>createHash("sha256").update(bytes).digest("hex");
if(sha(dockerfile)!==lock.dockerfileSha256)throw new Error("Pinned Dockerfile mismatch");
const archive=git("archive","--format=tar",lock.revision);
const output=resolve(destination);
if(!/^[A-Za-z0-9_./-]+$/.test(output))throw new Error("Context path must be an absolute simple filesystem path");
mkdirSync(output,{mode:0o700}); // Refuse an existing directory; never erase a working tree.
execFileSync("tar",["-xf","-","-C",output],{input:archive});
writeFileSync(`${output}/.table-source.json`,JSON.stringify({...lock,sourceArchiveSha256:sha(archive)},null,2)+"\n");
writeFileSync(`${output}.env`,`TABLE_SOURCE_CONTEXT=${output}\nTABLE_SOURCE_REVISION=${lock.revision}\nTABLE_SOURCE_TREE=${lock.tree}\n`,{mode:0o600,flag:"wx"});
console.log(`Exported ${lock.revision} (${lock.tree}); compose --env-file ${output}.env`);
