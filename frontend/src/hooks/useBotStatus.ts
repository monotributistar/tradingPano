import { useQuery } from "@tanstack/react-query";
import { fetchBotStatus } from "../api/client";

export function useBotStatus() {
  return useQuery({
    queryKey: ["botStatus"],
    queryFn: fetchBotStatus,
    refetchInterval: 5000,
  });
}
