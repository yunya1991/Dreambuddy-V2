export default function UIMapModuleCard(props: {
  title: string;
  description: string;
  bullets?: string[];
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ${props.className ?? ""}`}>
      <h3 className="text-lg font-semibold text-slate-900">{props.title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{props.description}</p>
      {props.bullets?.length ? (
        <ul className="mt-3 space-y-2 text-sm text-slate-700">
          {props.bullets.map((bullet) => (
            <li key={bullet}>• {bullet}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
