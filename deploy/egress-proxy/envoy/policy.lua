local exact_hosts = {
  ["allowed.internal"] = true,
}

local wildcard_hosts = {

}

local allowed_ports = {
  [8080] = true,
}

local function json_escape(value)
  return string.gsub(value or "", '"', '\"')
end

local function host_matches(host)
  if exact_hosts[host] == true then
    return true
  end
  for suffix, _ in pairs(wildcard_hosts) do
    local dotted_suffix = "." .. suffix
    if host ~= suffix and string.sub(host, -string.len(dotted_suffix)) == dotted_suffix then
      return true
    end
  end
  return false
end

local function audit(handle, reason, host, port)
  local method = json_escape(handle:headers():get(":method") or "")
  local message = '{"reason":"' .. json_escape(reason) ..
    '","target_host":"' .. json_escape(host) ..
    '","target_port":' .. tostring(port) ..
    ',"method":"' .. method .. '"}'
  handle:logInfo(message)
end

local function deny(handle, status, reason, host, port)
  audit(handle, reason, host, port)
  local headers = {[":status"] = tostring(status), ["content-type"] = "text/plain"}
  handle:respond(headers, reason)
end

function envoy_on_request(handle)
  local authority = handle:headers():get(":authority") or ""
  local host = string.lower(string.gsub(authority, ":.*$", ""))
  local port = tonumber(string.match(authority, ":(%d+)$") or "80")
  if host_matches(host) ~= true then
    return deny(handle, 403, "host_not_allowlisted", host, port)
  end
  if next(allowed_ports) ~= nil and allowed_ports[port] ~= true then
    return deny(handle, 403, "port_not_allowlisted", host, port)
  end
  handle:streamInfo():dynamicMetadata():set("envoy.filters.http.lua", "target_host", host)
  handle:streamInfo():dynamicMetadata():set("envoy.filters.http.lua", "target_port", port)
  audit(handle, "allowed", host, port)
end

function envoy_on_response(handle)
  local status = tonumber(handle:headers():get(":status") or "0")
  local location = handle:headers():get("location")
  if status >= 300 and status < 400 and location ~= nil then
    local metadata = handle:streamInfo():dynamicMetadata():get("envoy.filters.http.lua")
    local host = metadata["target_host"] or ""
    local port = metadata["target_port"] or 0
    handle:headers():replace(":status", "502")
    handle:headers():replace("content-type", "text/plain")
    handle:headers():remove("location")
    handle:body():setBytes("redirect_denied")
    audit(handle, "redirect_denied", host, port)
  end
end
