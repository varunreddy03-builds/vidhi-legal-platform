import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

/** Opens (creating once) the fictional sample matter to practise on. `madeMessage` is shown the first time it is created. */
export function useSample(madeMessage: string) {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => apiPost<{ matter_id: string; created: boolean }>("/demo/sample"),
    onSuccess: (r) => {
      if (r.created) toast.success(madeMessage);
      navigate(`/matters/${r.matter_id}`);
    },
    onError: (e) => toast.error(describe(e)),
  });
}
