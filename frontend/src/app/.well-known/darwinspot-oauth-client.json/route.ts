import { NextResponse } from "next/server";

export function GET(request: Request) {
  const origin = new URL(request.url).origin;
  const clientMetadataUrl = `${origin}/.well-known/darwinspot-oauth-client.json`;
  const callbackUrl = `${origin}/api/integrations/binance/callback`;

  return NextResponse.json(
    {
      client_id: clientMetadataUrl,
      client_name: "DarwinSpot",
      application_type: "web",
      redirect_uris: [callbackUrl],
      response_types: ["code"],
      grant_types: ["authorization_code", "refresh_token"],
      token_endpoint_auth_method: "none",
    },
    { headers: { "Cache-Control": "public, max-age=300" } },
  );
}
