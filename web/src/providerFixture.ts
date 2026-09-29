export function providerFixture(path: string) {
  return {
    environment_id:
      new URL(path, "http://fixture.local").searchParams.get(
        "environment_id",
      ) ?? "local",
    providers: { codex: { available: true }, claude: { available: true } },
  };
}
