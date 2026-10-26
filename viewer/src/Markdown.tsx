import type { ReactNode } from 'react';

// Deliberately limited renderer: React escapes all text; document HTML never executes.
function inline(text:string):ReactNode[] {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part,index) =>
    part.startsWith('`') ? <code key={index}>{part.slice(1,-1)}</code> :
    part.startsWith('**') ? <strong key={index}>{part.slice(2,-2)}</strong> : part);
}
export default function Markdown({text}:{text:string}) {
  const lines=text.split('\n'); const output:ReactNode[]=[]; let i=0;
  while(i<lines.length) {
    const line=lines[i]; const key=i;
    if(!line.trim()) {i++;continue;}
    if(line.startsWith('```')) {
      const code:string[]=[]; i++;
      while(i<lines.length&&!lines[i].startsWith('```')) code.push(lines[i++]);
      i++; output.push(<pre key={key}><code>{code.join('\n')}</code></pre>);continue;
    }
    const heading=line.match(/^(#{1,6})\s+(.*)$/);
    if(heading) { const content=inline(heading[2]); const level=heading[1].length;
      output.push(level===1?<h1 key={key}>{content}</h1>:level===2?<h2 key={key}>{content}</h2>:
        level===3?<h3 key={key}>{content}</h3>:<h4 key={key}>{content}</h4>);i++;continue;
    }
    if(line.includes('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1]??'')) {
      const split=(row:string)=>{
        let body=row.trim(); if(body.startsWith('|'))body=body.slice(1);
        if(body.endsWith('|')&&!body.endsWith('\\|'))body=body.slice(0,-1);
        const cells=[''];
        for(let at=0;at<body.length;at++){
          if(body[at]==='\\'&&body[at+1]==='|'){cells[cells.length-1]+='|';at++;}
          else if(body[at]==='|')cells.push('');
          else cells[cells.length-1]+=body[at];
        }
        return cells.map(cell=>cell.trim());
      };
      const headings=split(line); i+=2; const rows:string[][]=[];
      while(i<lines.length&&lines[i].includes('|')) rows.push(split(lines[i++]));
      output.push(<div className="table-scroll" key={key}><table><thead><tr>{headings.map((h,n)=><th key={n}>{inline(h)}</th>)}</tr></thead>
        <tbody>{rows.map((row,n)=><tr key={n}>{headings.map((_,c)=><td key={c}>{inline(row[c]??'')}</td>)}</tr>)}</tbody></table></div>);continue;
    }
    if(/^\s*([-*+]\s+|\d+[.)]\s+)/.test(line)) {
      const ordered=/^\s*\d/.test(line); const items:ReactNode[]=[];
      const firstNumber=ordered?Number(line.match(/^\s*(\d+)[.)]/)![1]):undefined;
      const sameKind=(value:string)=>ordered?/^\s*\d+[.)]\s+/.test(value):/^\s*[-*+]\s+/.test(value);
      while(i<lines.length&&sameKind(lines[i])) {
        const current=lines[i];const marker=ordered?Number(current.match(/^\s*(\d+)[.)]/)![1]):undefined;
        items.push(<li key={i} value={marker}>{inline(current.replace(/^\s*([-*+]\s+|\d+[.)]\s+)/,''))}</li>);
        i++;
        if(!lines[i]?.trim()){
          let next=i;while(next<lines.length&&!lines[next].trim())next++;
          if(next<lines.length&&sameKind(lines[next]))i=next;
        }
      }
      output.push(ordered?<ol key={key} start={firstNumber}>{items}</ol>:<ul key={key}>{items}</ul>);continue;
    }
    const paragraph=[line];i++;
    while(i<lines.length&&lines[i].trim()&&!/^(#|```|[-*+]\s|\d+[.)]\s)/.test(lines[i])) paragraph.push(lines[i++]);
    output.push(<p key={key}>{inline(paragraph.join(' '))}</p>);
  }
  return <article className="markdown">{output.length?output:<p className="muted">No readable text was found. Check document warnings.</p>}</article>;
}
