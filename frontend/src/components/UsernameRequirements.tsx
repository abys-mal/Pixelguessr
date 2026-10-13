export function UsernameRequirements({ id }: { id: string }) {
  return (
    <p className="field-help" id={id}>
      Up to 150 characters. Must be unique (case-insensitive), with no whitespace. Cannot end with -
      or _.
    </p>
  );
}
