import { useState } from "react";

function Transcript({ transcript, onWordClick, currentTime }) {
    const [searchWord, setSearchWord] = useState("");
    // Track which word index is being hovered
    const [hoveredIndex, setHoveredIndex] = useState(null);

    if (!transcript) return null;

    return (
        <>
            <h2>Transcript (click a word)</h2>
            <input 
                type="text" 
                placeholder="Search word..."
                value={searchWord}
                onChange={(e) => setSearchWord(e.target.value.toLowerCase())}
                style={{ marginBottom: "1rem", padding: "0.5rem" }}
            />
            
            <p style={{ lineHeight: "1.8", maxWidth: "100%", whiteSpace: "normal" }}>
                {transcript.map((w, i) => {
                    const normalizedWord = w.word.toLowerCase().replace(/[\.,!?']/g, "");
                    const isSearchMatch = searchWord && normalizedWord.includes(searchWord);
                    
                    // Logic for highlights
                    const isCurrentWord = currentTime >= w.start && currentTime <= w.end;
                    const isHovered = hoveredIndex === i;

                    // Determine background color priority
                    let backgroundColor = "transparent";
                    if (isSearchMatch) backgroundColor = "yellow";
                    if (isHovered) backgroundColor = "lightblue";
                    if (isCurrentWord) backgroundColor = "orange";

                    return (
                        <span
                            key={i}
                            onClick={() => onWordClick(w.start)}
                            onMouseEnter={() => setHoveredIndex(i)}
                            onMouseLeave={() => setHoveredIndex(null)}
                            style={{
                                cursor: "pointer",
                                marginRight: "4px",
                                borderRadius: "2px",
                                backgroundColor: backgroundColor,
                                // Transition makes the color change smooth
                                transition: "background-color 0.2s ease" 
                            }}                        
                        >
                            {w.word + " "}
                        </span>
                    );
                })}
            </p>
        </>
    );
}

export default Transcript;