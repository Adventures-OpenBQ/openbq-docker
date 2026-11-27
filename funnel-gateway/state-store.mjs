// SPDX-License-Identifier: Apache-2.0
import { request } from "node:http";
import { stateFile } from "./policy.mjs";
// Sixfold JSON escaping/UTF-8 replacement, 200 ASCII names, compact envelope.
export const STATE_LIST_RESPONSE_MAX = 6 * 2097152 + 200 * (96 + 6) + 11;

export function requestState(method, id, name, body, config, signal, version = null) {
  if (!/^\d{1,20}$/.test(id) || (name !== undefined && !stateFile(name)) ||
      !["GET", "PUT", "DELETE"].includes(method) || (method === "GET") !== (name === undefined)) {
    return Promise.reject(new Error("State unavailable"));
  }
  if (version && (method === "GET" || typeof version.writer !== "string" ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(version.writer) ||
      !Number.isSafeInteger(version.sequence) || version.sequence < 1)) {
    return Promise.reject(new Error("State unavailable"));
  }
  const url = new URL(`/_openbq/settings/v1/state/${id}${name === undefined ? "" : "/" + name}`, config.apiOrigin);
  return new Promise((resolve, reject) => {
    const fail = () => reject(new Error("State unavailable"));
    const req = request(url, { method, signal, headers: {
      Authorization: `Bearer ${config.token}`, Accept: "application/json",
      ...(version ? {"x-bdobb-state-writer": version.writer,
        "x-bdobb-state-sequence": String(version.sequence)} : {}),
      ...(body ? { "Content-Type": "application/json", "Content-Length": body.length } : {}),
    } }, res => {
      const status = res.statusCode, length = res.headers["content-length"];
      if (res.headers["content-encoding"] || (length !== undefined &&
          (!/^\d+$/.test(length) || Number(length) > STATE_LIST_RESPONSE_MAX)) ||
          !((method === "GET" && status === 200) || (method !== "GET" && [204, 409, 413].includes(status)))) {
        res.destroy(); fail(); return;
      }
      if (status === 204 && version && (res.headers["x-bdobb-state-writer"] !== version.writer ||
          res.headers["x-bdobb-state-sequence"] !== String(version.sequence))) {
        res.destroy(); fail(); return;
      }
      if (status !== 200) {
        res.resume(); res.on("end", () => resolve({status,
          ...(status === 204 && version ? {version: {writer: version.writer, sequence: version.sequence}} : {})}));
        res.on("error", fail); return;
      }
      const chunks = []; let size = 0;
      res.on("data", chunk => {
        size += chunk.length;
        if (size > STATE_LIST_RESPONSE_MAX) { res.destroy(); fail(); return; }
        chunks.push(chunk);
      });
      res.on("error", fail);
      res.on("end", () => {
        try {
          const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!value || !value.files || Array.isArray(value.files) || typeof value.files !== "object" ||
              !Object.entries(value.files).every(([key, text]) => stateFile(key) && typeof text === "string")) throw new Error();
          resolve({ status, json: { files: value.files } });
        } catch { fail(); }
      });
    });
    req.on("error", fail); req.end(body);
  });
}
