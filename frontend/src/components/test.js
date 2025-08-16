import React from 'react';

function Test() {
  return (
    <div>
      <h2>Sign Up</h2>
      <form>
        <div>
          <label>Username: </label>
          <input type="text" placeholder="Choose a username" />
        </div>
        <div>
          <label>Password: </label>
          <input type="password" placeholder="Choose a password" />
        </div>
        <button type="submit">Sign Up</button>
      </form>
    </div>
  );
}

export default Test;